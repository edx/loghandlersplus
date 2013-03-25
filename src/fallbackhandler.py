import logging
import logging.handlers
from datetime import datetime
from lambdahandler import LambdaHandler


class FallbackHandler(logging.Handler):
    '''FallbackHandler acts as a wrapper around the main_handler so that if it fails we handle requests using the fallback handlers.
    Working: 1. Service requests using main_handler
             2. If main_handler takes more than timeout seconds attempts times then it is taken out of main queue and start using fallback_handlers
             3. Readd the main_handler into the queue after retry_timeout seconds
             4. If at any point an exception is thrown, catch it using exception_handlers
    '''
    
    def __timeout (self, func, arg1, timeout_duration, it=None):
        ''' Calls func with argument arg1.
        Returns a tuple with first element a boolean indicating whether the function timed out and the second element an exception string if it occurred.

        Parameters:
            func: Function whose running time is to be monitered
            arg1: Argument to the function
            timeout_duration: Time interval after which TimeoutError is raised
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
        
        return (is_timeout, it.result)

    def __init__(self, main_handler, fallback_handlers, exception_handlers, timeout, attempts, retry_timeout):
        '''Parameters
            main_handler: The main log handler
            fallback_handlers: List of fallback handlers if main_handler times out
            exception_handlers: Exception handler if main handler throws exception
            timeout: Timeout
            attempts: Number of attempts before the handler is taken out into recharge queue
            retry_timeout: Time interval after which handlers in recharge queue are tried again
        '''
        logging.Handler.__init__(self)
        self.main_handler = main_handler
        self.fallback_handlers = fallback_handlers
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
        self.__maintimeoutcount = 0
        self.__queue = self.fallback_handlers[::-1]
        self.__queue.append(self.main_handler)
        self.__rechargequeue = []

    def emit(self, record):
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
            handlers_called = []
        else:
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

    fallbackhandlerok = LambdaHandler(lambda x: f_handlerok("fallback", x))
    fallbackhandlerbad = LambdaHandler(lambda x: f_handlerbad("fallback", x))
    fallbackhandlertimeout = LambdaHandler(lambda x: f_handlertimeout("fallback", x))

    defaulthandlerok = LambdaHandler(lambda x: f_handlerok("default", x))
    defaulthandlerbad = LambdaHandler(lambda x: f_handlerbad("default", x))
    defaulthandlertimeout = LambdaHandler(lambda x: f_handlertimeout("default", x))

    defaultexceptionhandler = LambdaHandler(lambda x: f_handlerok("exception", x))

    # Test case: Normal condition
    test1handler = FallbackHandler(mainhandlerok, fallback_handlers=[fallbackhandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test1handler)
    logger.error("TEST 1")
    logger.removeHandler(test1handler)
    verify("Main handler test", ['[main]start ok: TEST 1', '[main]finish ok: TEST 1'])

    # Test case: Main handler throws an exception
    print
    print "=== TEST 2: Main Handler Bad ==="
    test2handler = FallbackHandler(mainhandlerbad, fallback_handlers=[fallbackhandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test2handler)
    logger.error("TEST 2")
    logger.removeHandler(test2handler)

    # Test case: Main handler times out
    print
    print "=== TEST 3: Main Handler Timeout Fallback Handler OK ==="
    test3handler = FallbackHandler(mainhandlertimeout, fallback_handlers=[fallbackhandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=0.1)
    logger.addHandler(test3handler)
    for i in range(0, 5):
        logger.error("TEST 3-" + str(i))
    print "Waiting for main handler to back into queue..."
    for i in range(0, 10000000):
        pass
    for i in range(5, 7):
        logger.error("TEST 3-" + str(i))
    logger.removeHandler(test3handler)

    print
    print "=== TEST 4: Main Handler Timeout Fallback Handler Bad ==="
    test4handler = FallbackHandler(mainhandlertimeout, fallback_handlers=[fallbackhandlerbad, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test4handler)
    for i in range(0, 5):
        logger.error("TEST 4-" + str(i))
    logger.removeHandler(test4handler)

    print
    print "=== TEST 5: Main Handler Timeout Fallback Handler Timeout Default Handler OK ==="
    test5handler = FallbackHandler(mainhandlertimeout, fallback_handlers=[fallbackhandlertimeout, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test5handler)
    for i in range(0, 8):
        logger.error("TEST 5-" + str(i))
    logger.removeHandler(test5handler)

    print
    print "=== TEST 6: Main Handler Timeout Fallback Handler Timeout Default Handler Bad ==="
    test6handler = FallbackHandler(mainhandlertimeout, fallback_handlers=[fallbackhandlertimeout, defaulthandlerbad], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test6handler)
    for i in range(0, 8):
        logger.error("TEST 6-" + str(i))
    logger.removeHandler(test6handler)

    print
    print "=== TEST 7: Main Handler Timeout Fallback Handler Timeout Default Handler Timeout ==="
    test7handler = FallbackHandler(mainhandlertimeout, fallback_handlers=[fallbackhandlertimeout, defaulthandlertimeout], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test7handler)
    for i in range(0, 10):
        logger.error("TEST 7-" + str(i))
    logger.removeHandler(test7handler)

    print
    print "=== TEST 8: Load testing ==="
    test8handler = FallbackHandler(mainhandlertimeout, fallback_handlers=[fallbackhandlerok, defaulthandlerok], exception_handlers=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
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
