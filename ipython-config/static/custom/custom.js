// Make the notebook name and path available to the kernel
// as environment variables.

var initEnvironment = function(name,value) {
    try {
        var cmd = "import os\n" +
            "os.environ['" + name + "'] = '" + value + "'\n";
        IPython.notebook.kernel.execute(cmd, {}, {'silent' : true});
    }
    catch (error) {
        console.log("Couldn't set notebook name and path.");
    }
};

$([IPython.events]).on('status_started.Kernel', function() {
    initEnvironment('notebook_name', IPython.notebook.notebook_name);
    initEnvironment('notebook_path', IPython.notebook.notebook_path);
});

$([IPython.events]).on('notebook_renamed.Notebook', function(json) {
    initEnvironment('notebook_name', IPython.notebook.notebook_name);
    initEnvironment('notebook_path', IPython.notebook.notebook_path);
});
