import sys
from IPython.kernel.zmq.kernelapp import IPKernelApp
from IPython.kernel.zmq.ipkernel import Kernel

# Import activepapers.storage (which imports activepapers.execution)
# in order to have access to Python code from ActivePapers in the kernel.
import activepapers.storage

# A special kernel will intercept communication with the notebook
# server and transfer write access to the ActivePapers file to
# the process that needs it.
class ActivePapersKernel(Kernel):

    def __init__(self, **kwargs):
        super(ActivePapersKernel, self).__init__(**kwargs)

def main():
    """Run an IPKernel as an application"""
    app = IPKernelApp.instance()
    app.config.IPKernelApp.kernel_class = 'activepapers.ipkernel.ActivePapersKernel'
    app.initialize()
    app.start()
