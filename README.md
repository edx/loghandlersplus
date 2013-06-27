loghandlersplus
===============

Additional handlers for Python logging (Lambda, AWS SNS, AWS SQS). 

* Lambda handler is a generic handler to which one can pass a function
  which is called to handle log events.
* AWS SNS and SQS handlers will pipe to the respective services. As of
  this writing, SQS will handle around 60 requests per second per
  thread, while SNS while handle around 30 (linear scaling confirmed
  up to 10 threads). 
* Failsafe handler is a way of wrapping a handler in such a way that
  it won't take down your system. If a handler throws an exception,
  that exception is passed to a fallback handler. If a handler takes
  more than some period of time (e.g. http handler with the server
  backlogged), that handler is taken out of the pool for a while. This
  uses threads. Throughput with threads is 680-4500 calls per second
  on a T2400 (a laptop CPU from 2006).

To install, run: 

    python setup.py install

Note that the AWS handlers require boto. We explicitly do not include
this in requirements.txt. As the list of services grows, we would
prefer to only require packages installed for the specific services
used.

To give some context: The 30RPS/60RPS implies the latency is enough to 
cause a slight but noticable hit to performance if this were used as a 
back-end on a typical Django project with no further configuration 
changes. Thelinear scaling suggests that increasing the number of 
threads would bring performance back. 
