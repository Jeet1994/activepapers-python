import itertools

import os

from tornado import web

from IPython.html.services.notebooks.nbmanager import NotebookManager
from IPython.nbformat import current
from IPython.utils.traitlets import Bool, Unicode, TraitError
from IPython.utils import tz

from activepapers.storage import ActivePaper
from activepapers.utility import mod_time, timestamp

class ActivePapersNotebookManager(NotebookManager):

    active_paper_path = Unicode(config=True)
    active_paper_may_write = Bool(config=True)

    filename_ext = Unicode(u'')

    def __init__(self, **kwargs):
        super(ActivePapersNotebookManager, self).__init__(**kwargs)
        self.paper = None
        self.may_write = False

    def info_string(self):
        return "Serving notebooks from ActivePaper %s" % self.active_paper_path

    def get_os_path(self, name=None, path=''):
        # This is a quick hack to get started. We should create
        # an empty temporary directory without any write permissions
        # to enforce the "no local files" policy.
        return os.getcwd()

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
            timestamp(notebook_group)
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

    def is_hidden(self, path):
        """Does the API style path correspond to a hidden directory or file?
        
        Parameters
        ----------
        path : string
            The path to check. This is an API path (`/` separated,
            relative to base notebook-dir).
        
        Returns
        -------
        hidden : bool
            Whether the path is hidden.
        
        """
        # Nothing is hidden.
        return False

    def get_base_name(self, name):
        assert name.endswith(".ipynb")
        return name[:-6]

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
        assert len(path) == 0
        self.open_ap_read()
        notebook_group = self.get_notebook_group()
        if notebook_group is None:
            return False
        return self.get_base_name(name) in notebook_group

    def increment_filename(self, basename, path=''):
        """Increment a notebook name to make it unique.

        Parameters
        ----------
        basename : unicode
            The base name of a notebook (no extension .ipynb)
        path : unicode
            The URL path of the notebooks directory

        Returns
        -------
        filename : unicode
            The complete filename (with extension .ipynb) for
            a new notebook, guaranteed not to exist yet.
        """
        assert self.path_exists(path)

        for i in itertools.count():
            name = u'{basename}{i}{ext}'.format(basename=basename, i=i,
                                                ext=".ipynb")
            if not self.notebook_exists(name, path):
                break
        return name

    def list_notebooks(self, path=''):
        """Return a list of notebook dicts without content.

        This returns a list of dicts, each of the form::

            dict(notebook_id=notebook,name=name)

        This list of dicts should be sorted by name::

            data = sorted(data, key=lambda item: item['name'])
        """
        self.log.debug("list_notebooks '%s'", path)
        assert path == ''
        self.open_ap_read()
        notebook_group = self.get_notebook_group()
        if notebook_group is None:
            return []
        notebooks = [self.get_notebook_model(name+".ipynb", path, content=False)
                     for name in notebook_group]
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

        if not self.notebook_exists(name=name, path=path):
            raise web.HTTPError(404, u'Notebook does not exist: %s' % name)
        notebook_group = self.get_notebook_group()
        # Create the notebook model.
        model = dict(name=name, path=path)
        name = self.get_base_name(name)
        timestamp = mod_time(notebook_group[name]['json'])
        model['last_modified'] = tz.utcfromtimestamp(timestamp)
        timestamp = mod_time(notebook_group[name])
        model['created'] = tz.utcfromtimestamp(timestamp)
        if content is True:
            assert path == ''
            ds_path = 'notebooks/%s/json' % name
            with self.paper._open_internal_file(ds_path, 'r') as f:
                nb = current.read(f, u'json')
            self.mark_trusted_cells(nb, path, name)
            model['content'] = nb
        return model

    def list_dirs(self, path):
        """List the directory models for a given API style path."""
        return []

    def get_dir_model(self, name, path=''):
        """Get the directory model given a directory name and its API style path.
        
        The keys in the model should be:
        * name
        * path
        * last_modified
        * created
        * type='directory'
        """
        path = path.strip()
        if not self.path_exists(path):
            raise IOError('directory does not exist: %r' % path)
        notebook_group = self.get_notebook_group()
        timestamp = mod_time(notebook_group)
        # Create the directory model.
        model ={}
        model['name'] = name
        model['path'] = path
        model['last_modified'] = tz.utcfromtimestamp(timestamp)
        model['created'] = tz.utcfromtimestamp(timestamp)
        model['type'] = 'directory'
        self.log.debug("get_dir_model('%s', '%s') -> %s",
                       name, path, str(model))
        return model

    def save_notebook_model(self, model, name, path=''):
        """Save the notebook model and return the model with no content."""
        if 'content' not in model:
            raise web.HTTPError(400, u'No notebook JSON data provided')
        
        # One checkpoint should always exist
        if self.notebook_exists(name, path) \
           and not self.list_checkpoints(name, path):
            self.create_checkpoint(name, path)

        new_path = model.get('path', path)
        new_name = model.get('name', name)

        if path != new_path or name != new_name:
            self._rename_notebook(name, path, new_name, new_path)

        self.open_ap_read_write()
        notebook_group = self.get_notebook_group()
        new_name_base = self.get_base_name(new_name)
        if new_name_base not in notebook_group:
            notebook_group.create_group(new_name_base)
            timestamp(notebook_group[new_name_base])

        # Save the notebook to an internal file
        nb = current.to_notebook_json(model['content'])
        self.check_and_sign(nb, new_path, new_name)
        if 'name' in nb['metadata']:
            nb['metadata']['name'] = u''
        try:
            assert new_path == ''
            ds_path = 'notebooks/%s/json' % new_name_base
            self.log.debug("Autosaving notebook %s", ds_path)
            with self.paper._open_internal_file(ds_path, 'w') as f:
                current.write(nb, f, u'json')
        except Exception as e:
            raise web.HTTPError(400, u'Unexpected error while autosaving notebook: %s %s' % (ds_path, e))

        # Save .py script as well
        ds_path = 'notebooks/%s/%s/py' % (new_path, new_name_base)
        self.log.debug("Writing script %s", ds_path)
        try:
            with self.paper._open_internal_file(ds_path, 'w') as f:
                current.write(nb, f, u'py')
        except Exception as e:
            raise web.HTTPError(400, u'Unexpected error while saving notebook as script: %s %s' % (ds_path, e))

        model = self.get_notebook_model(new_name, new_path, content=False)
        self.log.debug("save_notebook_model -> %s", model)
        return model

    def _rename_notebook(self, name, path, new_name, new_path):
        """Rename a notebook."""
        assert path == ''
        assert new_path == ''
        notebook_group = self.get_notebook_group()
        notebook_group.move(self.get_base_name(name),
                            self.get_base_name(new_name))

    def update_notebook_model(self, model, name, path=''):
        """Update the notebook's path and/or name"""
        assert self.notebook_exists(name, path)

        new_name = model.get('name', name)
        new_path = model.get('path', path)
        if path != new_path or name != new_name:
            self._rename_notebook(name, path, new_name, new_path)
        model = self.get_notebook_model(new_name, new_path, content=False)
        return model

    def delete_notebook_model(self, name, path=''):
        """Delete notebook by name and path."""
        assert self.notebook_exists(name, path)
        notebook_group = self.get_notebook_group()
        del notebook_group[name]

    def create_checkpoint(self, name, path=''):
        """Create a checkpoint of the current state of a notebook

        Returns a dictionary with entries "id" and
        "last_modified" describing the checkpoint.
        """
        assert self.notebook_exists(name, path)
        assert path == ''
        
        notebook = self.get_notebook_group()[self.get_base_name(name)]
        checkpoints = [ds_name for ds_name in notebook
                       if ds_name.startswith('checkpoint-')]
        if checkpoints:
            highest = max(int(cp.split('-')[1]) for cp in checkpoints)
        else:
            highest = 0
        checkpoint_id = "checkpoint-%d" % (highest+1)
        timestamp = mod_time(notebook['json'])
        last_modified = tz.utcfromtimestamp(timestamp)
        notebook[checkpoint_id] = notebook['json']
        return dict(id=checkpoint_id, last_modified=last_modified)

    def list_checkpoints(self, name, path=''):
        """Return a list of checkpoints for a given notebook"""
        assert self.notebook_exists(name, path)

        notebook = self.get_notebook_group()[self.get_base_name(name)]
        checkpoints = [ds_name for ds_name in notebook
                       if ds_name.startswith('checkpoint-')]
        return [dict(id=cp,
                     last_modified=tz.utcfromtimestamp(mod_time(notebook[cp])))
                for cp in checkpoints]

    def restore_checkpoint(self, checkpoint_id, name, path=''):
        """Restore a notebook from one of its checkpoints"""
        assert self.notebook_exists(name, path)

        notebook = self.get_notebook_group()[self.get_base_name(name)]
        del notebook['json']
        notebook['json'] = notebook[checkpoint_id]

    def delete_checkpoint(self, checkpoint_id, name, path=''):
        """delete a checkpoint for a notebook"""
        assert self.notebook_exists(name, path)

        notebook = self.get_notebook_group()[self.get_base_name(name)]
        del notebook[checkpoint]
