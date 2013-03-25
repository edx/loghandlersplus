loghandlersplus
===============

Additional handlers for Python logging (Lambda, AWS SNS, AWS SQS). 

* Lambda handler is a generic handler to which one can pass a function
  which is called to handle log events.
* AWS SNS and SQS handlers will pipe to the respective services. As of
  this writing, SQS will handle around 60 requests per second per
  thread, while SNS while handle around 30 (linear scaling confirmed
  up to 10 threads). 
* Fallback handler is a way of wrapping a handler in such a way that
  it won't take down your system. If a handler throws an exception,
  that exception is passed to a fallback handler. If a handler takes
  more than some period of time (e.g. http handler with the server
  backlogged), that handler is taken out of the pool for a while.

To install, run: 

python setup.py install

Note that the AWS handlers require boto. We explicitly do not include
this in requirements.txt. As the list of services grows, we would
prefer to only require packages installed for the specific services
used.