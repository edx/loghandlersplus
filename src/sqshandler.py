import logging
import logging.handlers

from boto.sqs.connection import SQSConnection
from boto.sqs.message import Message
import boto.sns

class SQSHandler(logging.Handler):
    ''' A Python logging handler which sends messages to Amazon SQS. Note 
    that, in many cases, an SNSHandler, tied to SQS, is a better option. '''
    def __init__(self, queue="pmitros_dev", aws_key=None, secret_key=None):
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

if False: 
    logger = logging.getLogger('myapp')
    logger.addHandler(SQSHandler())
    logger.error("AAAA")
    logger.info("BBBB")
