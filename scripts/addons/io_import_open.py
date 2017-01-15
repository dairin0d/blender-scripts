#  ***** BEGIN GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#  ***** END GPL LICENSE BLOCK *****

# <pep8 compliant>

bl_info = {
    "name": "Import Open",
    "author": "dairin0d, moth3r",
    "version": (1, 0, 1),
    "blender": (2, 7, 8),
    "location": "",
    "description": "Open non-.blend files using active importers",
    "warning": "",
    "wiki_url": "http://wiki.blender.org/index.php/Extensions:2.6/Py/Scripts/Import-Export/ImportOpen",
    "tracker_url": "https://github.com/dairin0d/import-open/issues",
    "category": "Import-Export"}
#============================================================================#

import bpy

import os
import sys
import fnmatch

class ImporterInfo:
    def __init__(self, name, op_id, ext, glob):
        if name.lower().startswith("import "):
            name = name[len("import "):]
        self.name = name
        self.op_id = op_id
        self.ext = ext
        self.glob = glob
    
    def load(self, filepath):
        category_name, op_name = self.op_id.split(".")
        op_category = getattr(bpy.ops, category_name)
        op = getattr(op_category, op_name)
        op(filepath=filepath)

def iter_importers():
    categories = ["import_anim", "import_curve", "import_mesh", "import_scene"]
    for category_name in categories:
        op_category = getattr(bpy.ops, category_name)
        
        for name in dir(op_category):
            total_name = category_name + "." + name
            
            if "import" in total_name:
                op = getattr(op_category, name)
                
                yield total_name, op

def collect_importers():
    importers = []
    
    # Special case: Collada is built-in, resides
    # in an unconventional category, and has no
    # explicit ext/glob properties defined
    op_info = ImporterInfo("Collada", "wm.collada_export", ".dae", "*.dae")
    importers.append(op_info)
    
    for total_name, op in iter_importers():
        op_class = type(op.get_instance())
        rna = op.get_rna()
        
        op_info = ImporterInfo(rna.rna_type.name, total_name,
            getattr(op_class, "filename_ext", ""),
            getattr(rna, "filter_glob", ""))
        importers.append(op_info)
    
    return importers

def find_file_arg(argv):
    for arg in argv[1:]: # skip blender app
        if os.path.isfile(arg): return arg

def find_file_importer(filepath):
    filepath_lower = filepath.lower()
    for importer in collect_importers():
        for pattern in importer.glob.lower().split(";"):
            if fnmatch.fnmatch(filepath_lower, pattern):
                return importer

# Note: this will crash blender if invoked from scene_update_pre()
# (though scene_update_post() seems to be ok with this)
def clear_all_scenes(name="Scene"):
    scenes = list(bpy.data.scenes)
    empty_scene = bpy.data.scenes.new(name)
    for scene in scenes:
        bpy.data.scenes.remove(scene, do_unlink=True)
    empty_scene.name = name

def load_argv_file():
    filepath = find_file_arg(sys.argv)
    if not filepath: return
    importer = find_file_importer(filepath)
    if not importer: return
    clear_all_scenes()
    importer.load(filepath)

# Loading must be done during normal context
# (thus we must wait until Blender exits "Registering addons" mode)
@bpy.app.handlers.persistent
def scene_update_post(*args):
    bpy.app.handlers.scene_update_post.remove(scene_update_post)
    load_argv_file()

def register():
    bpy.app.handlers.scene_update_post.append(scene_update_post)

def unregister():
    pass
