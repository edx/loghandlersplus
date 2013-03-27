import logging
import logging.handlers
from datetime import datetime
from lambdahandler import LambdaHandler


class FailsafeHandler(logging.Handler):
    '''FailsafeHandler acts as a wrapper around another handler. It
    guards against exceptions and timeouts. As a result, we can use
    the HTTP, SNS, and SQS handlers without failures if the downstream
    services are down.

    Functionality: 
    1. Service requests default to using main_handler
    2. If main_handler takes more than /timeout/ seconds, it will be terminated. 
    3. If it times out more than /attempts/ times, then it is taken
       out of main queue, and we start using failsafe_handlers instead. We retry main_handler
       after /retry_timeout/ seconds
    4. If at any point an exception is thrown, catch it using exception_handlers

    Please note that Python does not give a way to kill threads. If
    this code is completely ignored, threads may built up (e.g. at
    attempts=3 and retry_timeout at 1 hour, you may accumulate up to
    three threads per hour). 
    '''
    
    def __timeout (self, func, arg1, timeout_duration, it=None):
        ''' Calls func with argument arg1.

        Returns a tuple with first element a boolean indicating
        whether the function timed out and the second element an
        exception string if it occurred.

        Parameters:
            func: Function whose running time is to be monitered
            arg1: Argument to the function
            timeout_duration: Time interval after which request times out
            it: An InterruptableThread instance
        '''
        import threading        
        class InterruptableThread(threading.Thread):
            def __init__ (self):
                threading.Thread.__init__(self)
                self.result = None
            def run (self):
                try:
                    func(arg1)
                except Exception, ex:
                    self.result = ex
        if it == None:
            it = InterruptableThread()
        it.start()        
        is_timeout = False
        it.join(timeout_duration) # blocking call
        if it.isAlive():
            is_timeout = True
            it.join()
        
        if is_timeout:
            return "Timeout"
        if it.result:
            return "Exception "+it.result
        return "Success"

    def __init__(self, main_handler, fallback_handlers, exception_handler, timeout, attempts, retry_timeout):
        '''Parameters
            main_handler: The main log handler
            fallback_handlers: List of failsafe handlers if main_handler times out
            exception_handlers: Exception handler if main handler throws exception
            timeout: Timeout
            attempts: Number of attempts before the handler is taken out into recharge queue
            retry_timeout: Time interval after which handlers in recharge queue are tried again
        '''
        logging.Handler.__init__(self)
        self.handlers = [main_handler] + fallback_handlers
        self.exception_handlers = exception_handlers
        self.timeout = timeout
        self.attempts = attempts
        self.retry_timeout = retry_timeout
        
        self.reset()
        
    def reset(self):
        ''' Reset the handler to revert to the main handler
        * Empties the recharge queue and resets the main queue

        Parameters: None 
        '''
        self.__timeouts = {}
        for fh in [self.main_handler] + self.fallback_handlers:
            self.__timeouts[fh] = { 'attempts' : 0, 
                                    'active' : True }

    def emit(self, record):
        for handler in self.handlers:
            # If the current handler is active, try to call it. 
            
            # If the current handler was inactive, but is past the retry timeout, try it. 
            # If it works, reset it. 
            if self.__timeouts[handler]['active'] == False and \
                    self.__timeouts[handler]['reset_time'] > datetime.now():
                res = self.__timeout(handler, record, self.timeout)
                if res == "Success":
                    self.__reset_handler(handler)
                    break
                if res == "Timeout":
                    self.__timeout_handler(handler)
            
            # If the current handler is inactive, go on to the next one
            # If the current handler is active, try it. 
            res = self.__timeout(handler, record, self.timeout)
            if res == "Timeout":
                self.__timeouts[handler].attempts = self.__timeouts[handler].attempts + 1
                if self.__timeouts[handler].attempts >= self.attempts: 
                    self.__timeout_handler(handler)
                continue
            break

        #print str(self.__queue)
        # Check to see if any handler is ready to be added to the main queue from recharge queue
        for rq in self.__rechargequeue[:]:
            dtd = datetime.now() - rq[1]
            if dtd.total_seconds() > self.retry_timeout:
                # if the current handler is the main handler add it to the end
                if self.__queue[-1] == self.main_handler:
                    self.__queue.insert(-2, rq[0])
                else:
                    self.__queue.append(rq[0])
                    self.__maintimeoutcount = 0
                self.__rechargequeue.remove(rq)


        if len(self.__queue) > 0:
            current_handler = self.__queue[-1]
            try:
                result = self.__timeout(current_handler.emit, record, self.timeout)

                if result[0]: # Check timeout
                    self.__maintimeoutcount += 1
                    ## TODO: Raise exception and re-emit event

                    if self.__maintimeoutcount >= self.attempts:
                        self.__rechargequeue.append([self.__queue.pop(), datetime.now()])
                        self.__maintimeoutcount = 0
                else:
                    self.__maintimeoutcount = 0
                if result[1] != None: # Check exception
                    raise Exception(result[1])
                
            except Exception, ex:
                self.exception_handlers.emit(record)
        else:   # No working handlers to service request, print to console
            print record.getMessage()
            
    def __getattr__ (self, name):
        ## Allows access to auxiliary methods/data in the main_handler
        return self.main_handler.name

if __name__ == '__main__':
    import time
    logger = logging.getLogger('myapp')

    handlers_called = []

    def verify(name, a):
        global handlers_called
        if handlers_called == a:
            print name + " OKAY"
            del handlers_called[:]
        else:
            print "     Got: ", handlers_called
            print "Expected: ", a
            raise Exception(name+" failed")

    def f_handlerok(name, x):
        handlers_called.append("["+name+"]start ok: " + x)
        handlers_called.append("["+name+"]finish ok: " + x)

    def f_handlerbad(name, x):
        handlers_called.append("["+name+"]start rbad: " + x)
        temp = 0/0 # Raise DivideByZero Exception
        handlers_called.append("["+name+"]finish bad: " + x)

    def f_handlertimeout(name, x):
        handlers_called.append("["+name+"]start rtimeout: " + x)
        time.sleep(1)
        handlers_called.append("["+name+"]start rtimeout: " + x)

    mainhandlerok = LambdaHandler(lambda x: f_handlerok("main", x))
    mainhandlerbad = LambdaHandler(lambda x: f_handlerbad("main", x))
    mainhandlertimeout = LambdaHandler(lambda x: f_handlertimeout("main", x))

    failsafehandlerok = LambdaHandler(lambda x: f_handlerok("failsafe", x))
    failsafehandlerbad = LambdaHandler(lambda x: f_handlerbad("failsafe", x))
    failsafehandlertimeout = LambdaHandler(lambda x: f_handlertimeout("failsafe", x))

    defaulthandlerok = LambdaHandler(lambda x: f_handlerok("default", x))
    defaulthandlerbad = LambdaHandler(lambda x: f_handlerbad("default", x))
    defaulthandlertimeout = LambdaHandler(lambda x: f_handlertimeout("default", x))

    defaultexceptionhandler = LambdaHandler(lambda x: f_handlerok("exception", x))

    # Test case: Normal condition
    test1handler = FailsafeHandler(mainhandlerok, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test1handler)
    logger.error("TEST 1")
    logger.removeHandler(test1handler)
    verify("Main handler test", ['[main]start ok: TEST 1', '[main]finish ok: TEST 1'])

    # Test case: Main handler throws an exception
    test2handler = FailsafeHandler(mainhandlerbad, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test2handler)
    logger.error("TEST 2")
    logger.removeHandler(test2handler)
    verify("Main handler throws an exception test", ['[main]start rbad: TEST 2', '[exception]start ok: TEST 2', '[exception]finish ok: TEST 2'])


    # Test case: Main handler times out
    ## This test case fails. 
    ## Failsafe handler is never called. 
    print
    print "=== TEST 3: Main Handler Timeout Failsafe Handler OK ==="
    test3handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=0.1)
    logger.addHandler(test3handler)
    for i in range(0, 5):
        logger.error("TEST 3-" + str(i))
    print "Waiting for main handler to back into queue..."
    for i in range(0, 10000000):
        pass
    for i in range(5, 7):
        logger.error("TEST 3-" + str(i))
    logger.removeHandler(test3handler)
    verify("Main handler times out test", [])
# ['[main]start rtimeout: TEST 3-0', '[main]start rtimeout: TEST 3-0', '[main]start rtimeout: TEST 3-1', '[main]start rtimeout: TEST 3-1', '[main]start rtimeout: TEST 3-2', '[main]start rtimeout: TEST 3-2', '[failsafe]start ok: TEST 3-3', '[failsafe]finish ok: TEST 3-3', '[failsafe]start ok: TEST 3-4', '[failsafe]finish ok: TEST 3-4', '[main]start rtimeout: TEST 3-5', '[main]start rtimeout: TEST 3-5', '[main]start rtimeout: TEST 3-6', '[main]start rtimeout: TEST 3-6']

    print handlers_called
    handlers_called = []

    print
    print "=== TEST 4: Main Handler Timeout Failsafe Handler Bad ==="
    test4handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlerbad, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test4handler)
    for i in range(0, 5):
        logger.error("TEST 4-" + str(i))
    logger.removeHandler(test4handler)
    print handlers_called
    handlers_called = []

    print
    print "=== TEST 5: Main Handler Timeout Failsafe Handler Timeout Default Handler OK ==="
    test5handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlertimeout, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test5handler)
    for i in range(0, 8):
        logger.error("TEST 5-" + str(i))
    logger.removeHandler(test5handler)
    print handlers_called
    handlers_called = []

    print
    print "=== TEST 6: Main Handler Timeout Failsafe Handler Timeout Default Handler Bad ==="
    test6handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlertimeout, defaulthandlerbad], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test6handler)
    for i in range(0, 8):
        logger.error("TEST 6-" + str(i))
    logger.removeHandler(test6handler)
    print handlers_called
    handlers_called = []

    print
    print "=== TEST 7: Main Handler Timeout Failsafe Handler Timeout Default Handler Timeout ==="
    test7handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlertimeout, defaulthandlertimeout], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test7handler)
    for i in range(0, 10):
        logger.error("TEST 7-" + str(i))
    logger.removeHandler(test7handler)
    print handlers_called
    handlers_called = []

    print
    print "=== TEST 8: Load testing ==="
    test8handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test8handler)
    import threading        
    class TestingThread(threading.Thread):
        def __init__ (self):
            threading.Thread.__init__(self)
        def run (self):
            logger.error("TEST 8");
    it = None
    t=time.time()
    for i in range(0, 10000):
        it = TestingThread()
        it.start()
        it.join()
    delta = time.time()-t
    tps = 10000./delta
    print delta, tps # Handles 680-4500 threads per second on a 7-year-old T2400
    if tps < 600:
        raise Exception("Performance not okay")
    logger.removeHandler(test8handler)
    verify("Load test", ['[failsafe]start ok: TEST 8', '[failsafe]finish ok: TEST 8']*10000)
