import logging
import logging.handlers

from boto.sqs.connection import SQSConnection
from boto.sqs.message import Message
import boto.sns

class SQSHandler(logging.Handler):
    ''' A Python logging handler which sends messages to Amazon SQS. Note 
    that, in many cases, an SNSHandler, tied to SQS, is a better option. '''
    def __init__(self, queue="sqs_handler_debug", aws_key=None, secret_key=None):
        ''' Sends log messages to SNS. Parameters: 
        * queue is the SQS queue. This will be created if it does not exist. 
        * Optional: aws_key and secret_key. If these don't exist, it will look 
          at the appropriate environment variables. 
        '''

        logging.Handler.__init__(self)
        if aws_key and secret_key:
            conn = SQSConnection(aws_key, secret_key)
        else:
            conn = SQSConnection()
        self.q = conn.create_queue(queue)
        
    def emit(self, record):
        m = Message()
        m.set_body(record.msg)
        self.q.write(m)

if __name__ == '__main__':
    logger = logging.getLogger('myapp')
    logger.addHandler(SQSHandler())
    logger.error("AAAA")
    logger.info("BBBB")
