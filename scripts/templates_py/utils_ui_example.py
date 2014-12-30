import bpy
from dairin0d.utils_ui import (NestedLayout, messagebox, tag_redraw)

class NestedLayoutTest(bpy.types.Panel):
    """Test of NestedLayout"""
    bl_label = "NestedLayout Test"
    bl_idname = "OBJECT_PT_nestedlayouttest"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"
    
    def draw(self, context):
        layout = NestedLayout(self.layout, self.bl_idname)

        obj = context.object
        
        # Standard NestedLayout usage:
        
        row = layout.row()
        row.label(text="Hello world!", icon='WORLD_DATA')

        row = layout.row()
        row.label(text="Active object is: " + obj.name)
        row = layout.row()
        row.prop(obj, "name")

        row = layout.row()
        row.operator("mesh.primitive_cube_add")
        
        # Structured NestedLayout usage:
        
        exit_layout = True
        
        with layout:
            layout.label("label 1")
            if exit_layout: layout.exit()
            layout.label("label 2") # won't be executed
        
        with layout.row(True)["main"]:
            layout.label("label 3")
            with layout.row(True)(enabled=False):
                layout.label("label 4")
                if exit_layout: layout.exit("main")
                layout.label("label 5") # won't be executed
            layout.label("label 6") # won't be executed
        
        with layout.fold("Foldable micro-panel", "box"):
            if layout.folded: layout.exit()
            layout.label("label 7")
            with layout.fold("Foldable 2"):
                layout.label("label 8") # not drawn if folded

class RedrawMessageBoxTest(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "scene.redraw_messagebox_test"
    bl_label = "Redraw/Messagebox Test"

    def execute(self, context):
        msg = """
1) Submission guidelines

By submitting code to this tracker, you agree that the code is (compatible with) GNU GPL 2 or later.
If you choose for a compatible non-GPL license, notify it in the patch.

Submitting patches in this tracker are very welcome!
To make timely and proper reviews possible, we'd recommend you to check on the guidelines below.
""".strip()
        messagebox(msg, 'ERROR', width=300, confirm=True, spacing=0.5)
        tag_redraw()
        return {'FINISHED'}

def register():
    bpy.utils.register_class(RedrawMessageBoxTest)
    bpy.utils.register_class(NestedLayoutTest)

def unregister():
    bpy.utils.unregister_class(RedrawMessageBoxTest)
    bpy.utils.unregister_class(NestedLayoutTest)

if __name__ == "__main__":
    register()
