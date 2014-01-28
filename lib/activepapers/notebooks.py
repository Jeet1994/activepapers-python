import itertools

from tornado import web

from IPython.html.services.notebooks.nbmanager import NotebookManager
from IPython.nbformat import current
from IPython.utils.traitlets import Bool, Unicode, TraitError
from IPython.utils import tz

from activepapers.storage import ActivePaper
from activepapers.utility import mod_time, stamp

class ActivePapersNotebookManager(NotebookManager):

    active_paper_path = Unicode(config=True)
    active_paper_may_write = Bool(config=True)

    filename_ext = Unicode(u'')

    def __init__(self, **kwargs):
        super(ActivePapersNotebookManager, self).__init__(**kwargs)
        self.paper = None
        self.may_write = False

    def open_ap_read(self):
        if self.paper is None:
            self.may_write = False
            self.paper = ActivePaper(self.active_paper_path, 'r')
        self.log.debug("ActivePaper %s open for reading",
                       self.active_paper_path)

    def open_ap_read_write(self):
        self.log.debug("open_ap_read_write: %s, %d",
                       self.active_paper_path,
                       self.active_paper_may_write)
        if not self.active_paper_may_write:
            self.log.debug('No write permission for ActivePaper %s'
                           % self.active_paper_path)
            raise web.HTTPError(404, u'ActivePaper %s is read-only'
                                % self.active_paper_path)
        if self.paper is not None:
            if not self.may_write:
                self.paper.close()
                self.paper = None
        if self.paper is None:
            self.may_write = True
            self.paper = ActivePaper(self.active_paper_path, 'r+')
        self.log.debug("ActivePaper %s open read-write", self.active_paper_path)

    def get_notebook_group(self):
        assert self.paper is not None
        notebook_group = self.paper.file.get('notebooks', None)
        if notebook_group is None and self.may_write:
            notebook_group = self.paper.file.create_group('notebooks')
        return notebook_group

    def path_exists(self, path):
        """Does the API-style path (directory) actually exist?
        
        Parameters
        ----------
        path : string
            The path to check. This is an API path (`/` separated,
            relative to base notebook-dir).
        
        Returns
        -------
        exists : bool
            Whether the path is indeed a directory.
        """
        # For now, place all notebooks into a single HDF5 group,
        # /notebooks. This means that the only valid path is the
        # empty path.
        return len(path) == 0

    def notebook_exists(self, name, path=''):
        """Returns a True if the notebook exists. Else, returns False.

        Parameters
        ----------
        name : string
            The name of the notebook you are checking.
        path : string
            The relative path to the notebook (with '/' as separator)

        Returns
        -------
        bool
        """
        if name.endswith('.ipynb'):
            self.log.debug("notebook_exists: removing extension from notebook name %s", name)
            name = name[:-6]
        path = path.strip('/')
        self.open_ap_read()
        notebook_group = self.get_notebook_group()
        if notebook_group is None:
            return False
        return name in notebook_group

    def increment_filename(self, basename, path=''):
        """Increment a notebook name to make it unique.
        
        Parameters
        ----------
        basename : unicode
            The name of a notebook
        path : unicode
            The URL path of the notebooks directory
        """
        assert path == ''
        notebook_group = self.get_notebook_group()
        for i in itertools.count():
            name = u'{basename}{i}'.format(basename=basename, i=i)
            if notebook_group is None or name not in notebook_group:
                break
        return name

    def list_notebooks(self, path=''):
        """Return a list of notebook dicts without content.

        This returns a list of dicts, each of the form::

            dict(notebook_id=notebook,name=name)

        This list of dicts should be sorted by name::

            data = sorted(data, key=lambda item: item['name'])
        """
        if path:
            raise ValueError("path is %s" % str(path))
        self.open_ap_read()
        notebook_group = self.get_notebook_group()
        if notebook_group is None:
            return []
        notebooks = []
        for name in notebook_group:
            model = self.get_notebook_model(name, path, content=False)
            notebooks.append(model)
        return sorted(notebooks, key=lambda item: item['name'])

    def get_notebook_model(self, name, path='', content=True):
        """ Takes a path and name for a notebook and returns its model
        
        Parameters
        ----------
        name : str
            the name of the notebook
        path : str
            the URL path that describes the relative path for
            the notebook
            
        Returns
        -------
        model : dict
            the notebook model. If contents=True, returns the 'contents' 
            dict in the model as well.
        """

        if name.endswith('.ipynb'):
            self.log.debug("get_notebook_model: removing extension from notebook name %s", name)
            name = name[:-6]
        path = path.strip('/')
        if not self.notebook_exists(name=name, path=path):
            raise web.HTTPError(404, u'Notebook does not exist: %s' % name)
        notebook_group = self.get_notebook_group()
        # Create the notebook model.
        model ={}
        model['name'] = name
        model['path'] = path
        timestamp = mod_time(notebook_group[name]['json'])
        model['last_modified'] = tz.utcfromtimestamp(timestamp)
        #model['created'] = created
        if content is True:
            assert path == ''
            ds_path = 'notebooks/%s/json' % name
            with self.paper._open_internal_file(ds_path, 'r') as f:
                model['content'] = current.read(f, u'json')
        return model

    def create_notebook_model(self, model=None, path=''):
        """Create a new notebook and return its model with no content."""
        path = path.strip('/')
        if model is None:
            model = {}
        if 'content' not in model:
            metadata = current.new_metadata(name=u'')
            model['content'] = current.new_notebook(metadata=metadata)
        if 'name' not in model:
            model['name'] = self.increment_filename('Untitled', path)
            
        model['path'] = path
        model = self.save_notebook_model(model, model['name'], model['path'])
        return model

    def save_notebook_model(self, model, name, path=''):
        """Save the notebook model and return the model with no content."""
        path = path.strip('/')

        if 'content' not in model:
            raise web.HTTPError(400, u'No notebook JSON data provided')
        
        new_path = model.get('path', path).strip('/')
        new_name = model.get('name', name)

        if path != new_path or name != new_name:
            self.rename_notebook(name, path, new_name, new_path)

        self.open_ap_read_write()
        notebook_group = self.get_notebook_group()
        if new_name not in notebook_group:
            notebook_group.create_group(new_name)

        # Save the notebook file
        nb = current.to_notebook_json(model['content'])
        if 'name' in nb['metadata']:
            nb['metadata']['name'] = u''
        try:
            assert new_path == ''
            ds_path = 'notebooks/%s/json' % new_name
            self.log.debug("Autosaving notebook %s", ds_path)
            with self.paper._open_internal_file(ds_path, 'w') as f:
                current.write(nb, f, u'json')
        except Exception as e:
            raise web.HTTPError(400, u'Unexpected error while autosaving notebook: %s %s' % (ds_path, e))

        # Save .py script as well
        ds_path = 'notebooks/%s/%s/py' % (new_path, new_name)
        self.log.debug("Writing script %s", ds_path)
        try:
            with self.paper._open_internal_file(ds_path, 'w') as f:
                current.write(nb, f, u'py')
        except Exception as e:
            raise web.HTTPError(400, u'Unexpected error while saving notebook as script: %s %s' % (ds_path, e))

        model = self.get_notebook_model(new_name, new_path, content=False)
        return model

    def rename_notebook(self, name, path, new_name, new_path):
        """Rename a notebook."""
        raise NotImplementedError

    # def load_notebook_names(self):
    #     """On startup load the notebook ids and names from OpenStack Swift.
    #     """
    #     raise NotImplementedError

    # def read_notebook_object(self, notebook_id):
    #     """Get the object representation of a notebook by notebook_id."""
    #     raise NotImplementedError

    # def write_notebook_object(self, nb, notebook_id=None):
    #     """Save an existing notebook object by notebook_id."""
    #     raise NotImplementedError

    # def delete_notebook(self, notebook_id):
    #     """Delete notebook by notebook_id.

    #     Also deletes checkpoints for the notebook.
    #     """
    #     raise NotImplementedError

    # def get_checkpoint_path(self, notebook_id, checkpoint_id):
    #     """Returns the canonical checkpoint path based on the notebook_id and
    #     checkpoint_id
    #     """
    #     raise NotImplementedError

    # def new_checkpoint_id(self):
    #     """Generate a new checkpoint_id and store its mapping."""
    #     raise NotImplementedError

    # def create_checkpoint(self, notebook_id):
    #     """Create a checkpoint of the current state of a notebook

    #     Returns a dictionary with a checkpoint_id and the timestamp from the
    #     last modification
    #     """
    #     raise NotImplementedError

    # def list_checkpoints(self, notebook_id):
    #     """Return a list of checkpoints for a given notebook"""
    #     raise NotImplementedError

    # def restore_checkpoint(self, notebook_id, checkpoint_id):
    #     """Restore a notebook from one of its checkpoints.

    #     Actually overwrites the existing notebook
    #     """
    #     raise NotImplementedError

    # def delete_checkpoint(self, notebook_id, checkpoint_id):
    #     """Delete a checkpoint for a notebook"""
    #     raise NotImplementedError

    def info_string(self):
        return "Serving notebooks from ActivePaper %s" % self.active_paper_path
