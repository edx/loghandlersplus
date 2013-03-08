import logging
import logging.handlers

class LambdaHandler(logging.Handler):
    ''' A simple, extendable handler for logging. Initialize with a function. 
    That function will be called to log events. '''
    def __init__(self, f):
        logging.Handler.__init__(self)
        self.f = f

    def emit(self, record):
        self.f(record.msg)

if False: 
    ''' Debug/test code. ''' 
    def p(x):
        print x

    logger = logging.getLogger('myapp')
    logger.addHandler(LambdaHandler(p))
    logger.error("AAAA")
    logger.info("BBBB")
