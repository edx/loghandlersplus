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
                print ex
                self.exception_handlers.emit(record)
        
            
        else:   # No working handlers to service request, print to console
            print record.getMessage()
            
    def __getattr__ (self, name):
        return self.main_handler.name

if __name__ == '__main__':
    logger = logging.getLogger('myapp')

    def f_mainhandlerok(x):
        print "_test_mainhandlerok: " + x

    def f_mainhandlerbad(x):
        print "_test_mainhandlerbad: " + x
       # print "_test_main_handlerbad: Raising DivideByZero Exception"
        print 0/0 # Raise DivideByZero Exception

    def f_mainhandlertimeout(x):
        print "_test_mainhandlertimeout: " + x
       # print "--- Long Loop --- "
        for i in range(0, 10000000):
            pass

    def f_fallbackhandlerok(x):
        print "_test_fallbackhandlerok: " + x

    def f_fallbackhandlerbad(x):
        print "_test_fallbackhanderbad: " + x
       # print "_test_fallbackhanderbad: Raising DivideByZero Exception"
        print 0/0

    def f_fallbackhandlertimeout(x):
        print "_test_fallbackhandlertimeout: " + x
        #print "--- Long Loop --- "
        for i in range(0, 10000000):
            pass
        
    def f_defaulthandlerok(x):
        print "_test_defaulthandlerok: " + x

    def f_defaulthandlerbad(x):
        print "_test_defaulthandlerbad: " + x
        print 0/0

    def f_defaulthandlertimeout(x):
        print "_test_defaulthandlertimeout: " + x
        for i in range(0, 10000000):
            pass

    def f_defaultexceptionhandler(x):
        print "_test_defaultexceptionhandlerok: " + x
    
    _mainhandlerok = LambdaHandler(f_mainhandlerok)
    _mainhandlerbad = LambdaHandler(f_mainhandlerbad)
    _mainhandlertimeout = LambdaHandler(f_mainhandlertimeout)
    _fallbackhandlerok = LambdaHandler(f_fallbackhandlerok)
    _fallbackhandlerbad = LambdaHandler(f_fallbackhandlerbad)
    _fallbackhandlertimeout = LambdaHandler(f_fallbackhandlertimeout)
    _defaulthandlerok = LambdaHandler(f_defaulthandlerok)
    _defaulthandlerbad = LambdaHandler(f_defaulthandlerbad)
    _defaulthandlertimeout = LambdaHandler(f_defaulthandlertimeout)
    _defaultexceptionhandler = LambdaHandler(f_defaultexceptionhandler)

    print "_mainhandlerok: " + str(_mainhandlerok)
    print "_fallbackhandlerok: " + str(_fallbackhandlerok)
    print "_defaulthandlerok: " + str(_defaulthandlerok)

    print
    print "=== TEST 1: Main Handler OK ==="
    test1handler = FallbackHandler(_mainhandlerok, fallback_handlers=[_fallbackhandlerok, _defaulthandlerok], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test1handler)
    logger.error("TEST 1")
    logger.removeHandler(test1handler)

    print
    print "=== TEST 2: Main Handler Bad ==="
    test2handler = FallbackHandler(_mainhandlerbad, fallback_handlers=[_fallbackhandlerok, _defaulthandlerok], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test2handler)
    logger.error("TEST 2")
    logger.removeHandler(test2handler)

    print
    print "=== TEST 3: Main Handler Timeout Fallback Handler OK ==="
    test3handler = FallbackHandler(_mainhandlertimeout, fallback_handlers=[_fallbackhandlerok, _defaulthandlerok], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=0.1)
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
    test4handler = FallbackHandler(_mainhandlertimeout, fallback_handlers=[_fallbackhandlerbad, _defaulthandlerok], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test4handler)
    for i in range(0, 5):
        logger.error("TEST 4-" + str(i))
    logger.removeHandler(test4handler)

    print
    print "=== TEST 5: Main Handler Timeout Fallback Handler Timeout Default Handler OK ==="
    test5handler = FallbackHandler(_mainhandlertimeout, fallback_handlers=[_fallbackhandlertimeout, _defaulthandlerok], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test5handler)
    for i in range(0, 8):
        logger.error("TEST 5-" + str(i))
    logger.removeHandler(test5handler)

    print
    print "=== TEST 6: Main Handler Timeout Fallback Handler Timeout Default Handler Bad ==="
    test6handler = FallbackHandler(_mainhandlertimeout, fallback_handlers=[_fallbackhandlertimeout, _defaulthandlerbad], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test6handler)
    for i in range(0, 8):
        logger.error("TEST 6-" + str(i))
    logger.removeHandler(test6handler)

    print
    print "=== TEST 7: Main Handler Timeout Fallback Handler Timeout Default Handler Timeout ==="
    test7handler = FallbackHandler(_mainhandlertimeout, fallback_handlers=[_fallbackhandlertimeout, _defaulthandlertimeout], exception_handlers=_defaultexceptionhandler, timeout=0.1, attempts=3, retry_timeout=60*60)
    logger.addHandler(test7handler)
    for i in range(0, 10):
        logger.error("TEST 7-" + str(i))
    logger.removeHandler(test7handler)

