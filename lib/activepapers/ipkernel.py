import os
import sys

from lockfile import LockFile

from IPython.kernel.zmq.kernelapp import IPKernelApp
from IPython.kernel.zmq.ipkernel import Kernel
from IPython.config.loader import Config
from IPython.utils.traitlets import Bool, Unicode, TraitError

# Import activepapers.storage and activepapers.execution
# in order to have access to Python code from ActivePapers in the kernel.
import activepapers.storage
import activepapers.execution

# A special kernel will intercept communication with the notebook
# server and transfer write access to the ActivePapers file to
# the process that needs it.
class ActivePapersKernel(Kernel, activepapers.execution.RestrictedExecutable):

    active_paper_path = Unicode(config=True)
    active_paper_may_write = Bool(config=True)

    def __init__(self, **kwargs):
        super(ActivePapersKernel, self).__init__(**kwargs)
        if self.active_paper_may_write:
            self.lock = LockFile(self.active_paper_path)
            self.mode = 'r+'
        else:
            self.lock = None
            self.mode = 'r'
        self.has_notebook_name = False

    def execute_request(self, stream, ident, parent):
        content = parent[u'content']
        code = content[u'code']
        if code.startswith("import os as _activepapers_os_"):
            self.log.debug("Special exec request in '%s' for '%s'",
                           self.active_paper_path, code)
            super(ActivePapersKernel, self).execute_request(stream, ident,
                                                            parent)
            self.log.debug("Exec request handled.")
            self.has_notebook_name = True
        else:
            assert self.has_notebook_name
            self.log.debug("Exec request in '%s' for '%s'",
                           self.active_paper_path, code)
            if self.lock is not None:
                self.lock.acquire()
            self.paper = activepapers.storage.ActivePaper(self.active_paper_path,
                                                          self.mode)
            h5path = '/'.join(["/notebooks",
                               os.environ['notebook_path'],
                               os.environ['notebook_name'],])
            paper_id = self._prepare_execution(h5path)
            super(ActivePapersKernel, self).execute_request(stream, ident,
                                                            parent)
            self._cleanup_execution(h5path, paper_id)
            self.paper.close()
            if self.lock is not None:
                self.lock.release()
            self.log.debug("Exec request handled.")

    def dependency_attributes(self):
        h5path = '/'.join(["/notebooks",
                           os.environ['notebook_path'],
                           os.environ['notebook_name'],])
        return self._dependency_attributes(h5path)

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
    del sys.argv[3:]
    app = IPKernelApp.instance(config=c)
    app.initialize()
    app.start()
