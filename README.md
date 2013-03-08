loghandlersplus
===============

Additional handlers for Python logging (Lambda, AWS SNS, AWS SQS). 

* Lambda logger is a generic logger to which one can pass a function
  which is called to handle log events.
* AWS SNS and SQS loggers will pipe to the respective services. As of
  this writing, SQS will handle around 60 requests per second per
  thread, while SNS while handle around 30 (linear scaling confirmed
  up to 10 threads). 

To install, run: 

python setup.py install

Note that the AWS loggers require boto. We explicitly do not include
this in requirements.txt. As the list of services grows, we would
prefer to only require packages installed for the specific services
used.