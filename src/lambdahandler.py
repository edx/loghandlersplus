import logging
import logging.handlers

class LambdaHandler(logging.Handler):
    ''' A simple, extendable handler for logging. Initialize with a function. 
    That function will be called to log events. '''
    def __init__(self, f):
        ''' Takes a single parameter -- a function which should take a string parameter. 
        Simplest example for a console logger: 

        def p(x): 
           print x

        console_handler = LambdaHandler(p)
        '''
        logging.Handler.__init__(self)
        self.f = f

    def emit(self, record):
        self.f(record.msg)

if __name__ == '__main__':
    ''' Debug/test code. ''' 
    def p(x):
        print x

    logger = logging.getLogger('myapp')
    logger.addHandler(LambdaHandler(p))
    logger.error("AAAA")
    logger.info("BBBB")
