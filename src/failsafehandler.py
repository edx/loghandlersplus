import logging
import logging.handlers
import time
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
    
    def __timeout (self, handler, record, timeout_duration):
        ''' Calls handler with argument record.

        Returns a tuple with first element a boolean indicating
        whether the function timed out and the second element an
        exception string if it occurred.

        Parameters:
            handler: Function whose running time is to be monitered
            record: Argument to the function
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
                    handler(record)
                except Exception, ex:
                    self.result = ex
        it = InterruptableThread()
        it.start()        
        is_timeout = False
        it.join(timeout_duration) # blocking call
        if it.isAlive():
            is_timeout = True
        
        if is_timeout:
            return "Timeout"
        if it.result:
            self.exception_handler.emit(record)
            return "Exception "+str(it.result)
        return "Success"

    def __init__(self, main_handler, fallback_handlers, exception_handler, timeout, attempts, retry_timeout):
        '''Parameters
            main_handler: The main log handler
            fallback_handlers: List of failsafe handlers if main_handler times out
            exception_handler: Exception handler if main handler throws exception
            timeout: Timeout
            attempts: Number of attempts before the handler is taken out into recharge queue
            retry_timeout: Time interval after which handlers in recharge queue are tried again
        '''
        logging.Handler.__init__(self)
        self.handlers = [main_handler] + fallback_handlers
        self.exception_handler = exception_handler
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
        for fh in self.handlers:
            self.__timeouts[fh] = {}
            self.__reset_handler(fh)

    def __timeout_handler(self, handler):
        self.__timeouts[handler]['active'] = False
        self.__timeouts[handler]['reset_time'] = time.time() + self.retry_timeout

    def __reset_handler(self, handler):
        self.__timeouts[handler]['active'] = True
        self.__timeouts[handler]['attempts'] = 0

    def emit(self, record):
        handled = False
        for handler in self.handlers:
            # If the current handler was inactive, but is past the retry timeout, try it. 
            # If it works, reset it. 
            if not self.__timeouts[handler]['active'] and \
                    self.__timeouts[handler]['reset_time'] < time.time():
                res = self.__timeout(handler.emit, record, self.timeout)
                if res == "Success":
                    self.__reset_handler(handler)
                    handled = True
                    break
                if res == "Timeout":
                    self.__timeout_handler(handler)
                    continue
                # exception
                break
            elif self.__timeouts[handler]['attempts'] > 0 and self.__timeouts[handler]['reset_time'] < time.time(): 
                self.__timeouts[handler]['attempts'] = 0

            # If the current handler is inactive, and it's not past
            # the timeout, go on to the next one
            if not self.__timeouts[handler]['active']:
                continue

            # If the current handler is active, try it. 
            res = self.__timeout(handler.emit, record, self.timeout)
            if res == "Timeout":
                self.__timeouts[handler]['attempts'] = self.__timeouts[handler]['attempts'] + 1
                self.__timeouts[handler]['reset_time'] = time.time() + self.retry_timeout
                if self.__timeouts[handler]['attempts'] >= self.attempts: 
                    self.__timeout_handler(handler)
                continue
            handled = True
            break
            
    def __getattr__ (self, name):
        ## Allows access to auxiliary methods/data in the main_handler
        if name=="__timeouts":
            return self.__timeouts
        return getattr(self.main_handler, name)

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
        handlers_called.append("["+name+"]finish rtimeout: " + x)

    mainhandlerok = LambdaHandler(lambda x: f_handlerok("main", x))
    mainhandlerbad = LambdaHandler(lambda x: f_handlerbad("main", x))
    mainhandlertimeout = LambdaHandler(lambda x: f_handlertimeout("main", x))
    mainhandlerusuallytimeout = LambdaHandler(lambda x: f_handlertimeout("main", x) if x!='okay' else f_handlerok("main", x))

    failsafehandlerok = LambdaHandler(lambda x: f_handlerok("failsafe", x))
    failsafehandlerbad = LambdaHandler(lambda x: f_handlerbad("failsafe", x))
    failsafehandlertimeout = LambdaHandler(lambda x: f_handlertimeout("failsafe", x))

    defaulthandlerok = LambdaHandler(lambda x: f_handlerok("default", x))
    defaulthandlerbad = LambdaHandler(lambda x: f_handlerbad("default", x))
    defaulthandlertimeout = LambdaHandler(lambda x: f_handlertimeout("default", x))

    defaultexceptionhandler = LambdaHandler(lambda x: f_handlerok("exception", x))

    # Test case: Handler times out after 3 events. 
    # We send 4, and confirm timeout. 
    # Wait for reset
    # Send 2
    # Wait for reset
    # Send 4 events. Confirm only fourth event times out. 
    test0handler = FailsafeHandler(mainhandlerusuallytimeout, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=0.9)
    logger.addHandler(test0handler)
    logger.error("TEST 1a")
    logger.error("TEST 1b")
    logger.error("TEST 1c")
    logger.error("TEST 1d") # Dropped
    time.sleep(1)
    logger.error("okay")
    logger.error("TEST 2a")
    logger.error("TEST 2b")
    time.sleep(1)
    logger.error("okay")
    logger.error("TEST 3a")
    logger.error("TEST 3b")
    logger.error("TEST 3c")
    logger.error("TEST 3d") # Dropped
    time.sleep(2)

    logger.removeHandler(test0handler)
    if set(handlers_called) == set(['[main]start rtimeout: TEST 1a', '[failsafe]start ok: TEST 1a', '[failsafe]finish ok: TEST 1a', '[main]start rtimeout: TEST 1b', '[failsafe]start ok: TEST 1b', '[failsafe]finish ok: TEST 1b', '[main]start rtimeout: TEST 1c', '[failsafe]start ok: TEST 1c', '[failsafe]finish ok: TEST 1c', '[failsafe]start ok: TEST 1d', '[failsafe]finish ok: TEST 1d', '[main]finish rtimeout: TEST 1a', '[main]finish rtimeout: TEST 1b', '[main]finish rtimeout: TEST 1c', '[main]start ok: okay', '[main]finish ok: okay', '[main]start rtimeout: TEST 2a', '[failsafe]start ok: TEST 2a', '[failsafe]finish ok: TEST 2a', '[main]start rtimeout: TEST 2b', '[failsafe]start ok: TEST 2b', '[failsafe]finish ok: TEST 2b', '[main]finish rtimeout: TEST 2a', '[main]finish rtimeout: TEST 2b', '[main]start ok: okay', '[main]finish ok: okay', '[main]start rtimeout: TEST 3a', '[failsafe]start ok: TEST 3a', '[failsafe]finish ok: TEST 3a', '[main]start rtimeout: TEST 3b', '[failsafe]start ok: TEST 3b', '[failsafe]finish ok: TEST 3b', '[main]start rtimeout: TEST 3c', '[failsafe]start ok: TEST 3c', '[failsafe]finish ok: TEST 3c', '[failsafe]start ok: TEST 3d', '[failsafe]finish ok: TEST 3d', '[main]finish rtimeout: TEST 3a', '[main]finish rtimeout: TEST 3b', '[main]finish rtimeout: TEST 3c']): 
        print "Reset timeout okay"
    else:
        print handlers_called
        raise Exception("Reset timeout fails")
    del handlers_called[:]

    # Test case: Normal condition
    test1handler = FailsafeHandler(mainhandlerok, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test1handler)
    logger.error("TEST 1")
    logger.removeHandler(test1handler)
    verify("Main handler test", ['[main]start ok: TEST 1', '[main]finish ok: TEST 1'])

    # Test case: Main handler throws an exception
    test2handler = FailsafeHandler(mainhandlerbad, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test2handler)
    logger.error("TEST 2")
    logger.removeHandler(test2handler)
    verify("Main handler throws an exception test", ['[main]start rbad: TEST 2', '[exception]start ok: TEST 2', '[exception]finish ok: TEST 2'])

    # Test case: Main handler times out
    ## This test case fails. 
    ## Failsafe handler is never called. 
    test3handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=1)
    logger.addHandler(test3handler)
    for i in range(0, 3): # First three calls time out
        t=time.time()
        logger.error("TEST 3-" + str(i))
        delta = time.time() - t 
        if delta > 0.15 or delta < 0.1: 
            raise Exception("Timeout failed "+str(delta))

    for i in range(3, 5): # These go fast -- we've taken out of the queue
        t=time.time()
        logger.error("TEST 3-" + str(i))
        delta = time.time() - t 
        if delta > 0.05:
            raise Exception("Timeout failed "+str(delta))

    print "Waiting for main handler to back into queue..."
    time.sleep(1)

    for i in range(6, 7): # We try again, slowly
        t=time.time()
        logger.error("TEST 3-" + str(i))
        delta = time.time() - t 
        if delta > 0.15 or delta < 0.1: 
            raise Exception("Timeout failed "+str(delta))

    for i in range(7, 12): # And, again, at a sprint. 
        t=time.time()
        logger.error("TEST 3-" + str(i))
        delta = time.time() - t 
        if delta > 0.05:
            raise Exception("Timeout failed "+str(delta))

    print "Waiting for all threads to finish"
    time.sleep(1)

    logger.removeHandler(test3handler)
    # Yes. I checked all of these by hand. 
    # I have not confirmed whether the order may ever change, but I think it should not. 
    verify("Main handler times out test", ['[main]start rtimeout: TEST 3-0', '[failsafe]start ok: TEST 3-0', '[failsafe]finish ok: TEST 3-0', '[main]start rtimeout: TEST 3-1', '[failsafe]start ok: TEST 3-1', '[failsafe]finish ok: TEST 3-1', '[main]start rtimeout: TEST 3-2', '[failsafe]start ok: TEST 3-2', '[failsafe]finish ok: TEST 3-2', '[failsafe]start ok: TEST 3-3', '[failsafe]finish ok: TEST 3-3', '[failsafe]start ok: TEST 3-4', '[failsafe]finish ok: TEST 3-4', '[main]finish rtimeout: TEST 3-0', '[main]finish rtimeout: TEST 3-1', '[main]finish rtimeout: TEST 3-2', '[main]start rtimeout: TEST 3-6', '[failsafe]start ok: TEST 3-6', '[failsafe]finish ok: TEST 3-6', '[failsafe]start ok: TEST 3-7', '[failsafe]finish ok: TEST 3-7', '[failsafe]start ok: TEST 3-8', '[failsafe]finish ok: TEST 3-8', '[failsafe]start ok: TEST 3-9', '[failsafe]finish ok: TEST 3-9', '[failsafe]start ok: TEST 3-10', '[failsafe]finish ok: TEST 3-10', '[failsafe]start ok: TEST 3-11', '[failsafe]finish ok: TEST 3-11', '[main]finish rtimeout: TEST 3-6'])

    test4handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlerbad, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test4handler)
    for i in range(0, 5):
        logger.error("TEST 4-" + str(i))
    logger.removeHandler(test4handler)
    time.sleep(1)
    verify("Main handler times out, fallback handler raises an exception", ['[main]start rtimeout: TEST 4-0', '[failsafe]start rbad: TEST 4-0', '[exception]start ok: TEST 4-0', '[exception]finish ok: TEST 4-0', '[main]start rtimeout: TEST 4-1', '[failsafe]start rbad: TEST 4-1', '[exception]start ok: TEST 4-1', '[exception]finish ok: TEST 4-1', '[main]start rtimeout: TEST 4-2', '[failsafe]start rbad: TEST 4-2', '[exception]start ok: TEST 4-2', '[exception]finish ok: TEST 4-2', '[failsafe]start rbad: TEST 4-3', '[exception]start ok: TEST 4-3', '[exception]finish ok: TEST 4-3', '[failsafe]start rbad: TEST 4-4', '[exception]start ok: TEST 4-4', '[exception]finish ok: TEST 4-4', '[main]finish rtimeout: TEST 4-0', '[main]finish rtimeout: TEST 4-1', '[main]finish rtimeout: TEST 4-2'])

    test5handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlertimeout, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test5handler)
    for i in range(0, 8):
        logger.error("TEST 5-" + str(i))
    logger.removeHandler(test5handler)
    time.sleep(1)

    # Note: I *think* the order should be maintained, but I have not
    # verified for some of the tougher test whether threading issues
    # might not change the order in which these return.  Test case
    # failure might not imply code failure; might just be a test
    # failure.
    verify("Main handler and fallback handler both time out", ['[main]start rtimeout: TEST 5-0', '[failsafe]start rtimeout: TEST 5-0', '[default]start ok: TEST 5-0', '[default]finish ok: TEST 5-0', '[main]start rtimeout: TEST 5-1', '[failsafe]start rtimeout: TEST 5-1', '[default]start ok: TEST 5-1', '[default]finish ok: TEST 5-1', '[main]start rtimeout: TEST 5-2', '[failsafe]start rtimeout: TEST 5-2', '[default]start ok: TEST 5-2', '[default]finish ok: TEST 5-2', '[default]start ok: TEST 5-3', '[default]finish ok: TEST 5-3', '[default]start ok: TEST 5-4', '[default]finish ok: TEST 5-4', '[default]start ok: TEST 5-5', '[default]finish ok: TEST 5-5', '[default]start ok: TEST 5-6', '[default]finish ok: TEST 5-6', '[default]start ok: TEST 5-7', '[default]finish ok: TEST 5-7', '[main]finish rtimeout: TEST 5-0', '[failsafe]finish rtimeout: TEST 5-0', '[main]finish rtimeout: TEST 5-1', '[failsafe]finish rtimeout: TEST 5-1', '[main]finish rtimeout: TEST 5-2', '[failsafe]finish rtimeout: TEST 5-2'])

    test6handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlertimeout, defaulthandlerbad], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test6handler)
    for i in range(0, 8):
        logger.error("TEST 6-" + str(i))
    logger.removeHandler(test6handler)
    time.sleep(1)
    verify("Main handler and fallback handler both time out, and second fallback handler throws an exception", ['[main]start rtimeout: TEST 6-0', '[failsafe]start rtimeout: TEST 6-0', '[default]start rbad: TEST 6-0', '[exception]start ok: TEST 6-0', '[exception]finish ok: TEST 6-0', '[main]start rtimeout: TEST 6-1', '[failsafe]start rtimeout: TEST 6-1', '[default]start rbad: TEST 6-1', '[exception]start ok: TEST 6-1', '[exception]finish ok: TEST 6-1', '[main]start rtimeout: TEST 6-2', '[failsafe]start rtimeout: TEST 6-2', '[default]start rbad: TEST 6-2', '[exception]start ok: TEST 6-2', '[exception]finish ok: TEST 6-2', '[default]start rbad: TEST 6-3', '[exception]start ok: TEST 6-3', '[exception]finish ok: TEST 6-3', '[default]start rbad: TEST 6-4', '[exception]start ok: TEST 6-4', '[exception]finish ok: TEST 6-4', '[default]start rbad: TEST 6-5', '[exception]start ok: TEST 6-5', '[exception]finish ok: TEST 6-5', '[default]start rbad: TEST 6-6', '[exception]start ok: TEST 6-6', '[exception]finish ok: TEST 6-6', '[default]start rbad: TEST 6-7', '[exception]start ok: TEST 6-7', '[exception]finish ok: TEST 6-7', '[main]finish rtimeout: TEST 6-0', '[failsafe]finish rtimeout: TEST 6-0', '[main]finish rtimeout: TEST 6-1', '[failsafe]finish rtimeout: TEST 6-1', '[main]finish rtimeout: TEST 6-2', '[failsafe]finish rtimeout: TEST 6-2'])

    test7handler = FailsafeHandler(mainhandlertimeout, fallback_handlers=[failsafehandlertimeout, defaulthandlertimeout], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test7handler)
    for i in range(0, 10):
        logger.error("TEST 7-" + str(i))
    logger.removeHandler(test7handler)
    time.sleep(1)
    
    verify("All handlers time out. This one is tricky, since this is never logged. Final fallback handler should log this.", ['[main]start rtimeout: TEST 7-0', '[failsafe]start rtimeout: TEST 7-0', '[default]start rtimeout: TEST 7-0', '[main]start rtimeout: TEST 7-1', '[failsafe]start rtimeout: TEST 7-1', '[default]start rtimeout: TEST 7-1', '[main]start rtimeout: TEST 7-2', '[failsafe]start rtimeout: TEST 7-2', '[default]start rtimeout: TEST 7-2', '[main]finish rtimeout: TEST 7-0', '[failsafe]finish rtimeout: TEST 7-0', '[default]finish rtimeout: TEST 7-0', '[main]finish rtimeout: TEST 7-1', '[failsafe]finish rtimeout: TEST 7-1', '[default]finish rtimeout: TEST 7-1', '[main]finish rtimeout: TEST 7-2', '[failsafe]finish rtimeout: TEST 7-2', '[default]finish rtimeout: TEST 7-2'])

    test7handler = FailsafeHandler(mainhandlerok, fallback_handlers=[failsafehandlerok, defaulthandlerok], exception_handler=defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test7handler)

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
    if tps < 600:
        raise Exception("Performance not okay")
    print "Ran 10000 threads in ", delta," for ", tps, " threads per second" # Handles 680-4500 threads per second on a 7-year-old T2400
    verify("Load test okay", ['[main]start ok: TEST 8', '[main]finish ok: TEST 8']*10000)
