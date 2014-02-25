import sys
from IPython.kernel.zmq.kernelapp import IPKernelApp
from IPython.kernel.zmq.ipkernel import Kernel
from IPython.config.loader import Config
from IPython.utils.traitlets import Bool, Unicode, TraitError

# Import activepapers.storage (which imports activepapers.execution)
# in order to have access to Python code from ActivePapers in the kernel.
import activepapers.storage

# A special kernel will intercept communication with the notebook
# server and transfer write access to the ActivePapers file to
# the process that needs it.
class ActivePapersKernel(Kernel):

    active_paper_path = Unicode(config=True)
    active_paper_may_write = Bool(config=True)

    def __init__(self, **kwargs):
        super(ActivePapersKernel, self).__init__(**kwargs)

    def execute_request(self, stream, ident, parent):
        content = parent[u'content']
        code = content[u'code']
        self.log.debug("Exec request in '%s' for '%s'",
                       self.active_paper_path, code)
        super(ActivePapersKernel, self).execute_request(stream, ident, parent)
        self.log.debug("Exec request handled.")

def main():
    """Run an IPKernel as an application"""
    import sys
    # The value of sys.argv is set in cli.ipython_notebook to
    #    ['-c', '-f', '{connection_file}',
    #     active_paper_path, active_paper_may_write]
    assert len(sys.argv) == 5
    c = Config()
    c.IPKernelApp.kernel_class = 'activepapers.ipkernel.ActivePapersKernel'
    c.IPKernelApp.log_level='DEBUG'
    c.ActivePapersKernel.active_paper_path = sys.argv[3]
    c.ActivePapersKernel.active_paper_may_write = bool(int(sys.argv[4]))
    app = IPKernelApp.instance(config=c)
    app.initialize(sys.argv[:3])
    app.start()
