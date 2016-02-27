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

bl_info = {
    "name": "Enhanced 3D Cursor WRK",
    "description": "Cursor history and bookmarks; drag/snap cursor.",
    "author": "dairin0d",
    "version": (3, 0, 0),
    "blender": (2, 7, 0),
    "location": "View3D > Action mouse; F10; Properties panel",
    "warning": "",
    "wiki_url": "http://wiki.blender.org/index.php/Extensions:2.6/Py/"
        "Scripts/3D_interaction/Enhanced_3D_Cursor",
    "tracker_url": "https://developer.blender.org/T28451",
    "category": "3D View"}
#============================================================================#

if "dairin0d" in locals():
    import imp
    imp.reload(dairin0d)
    imp.reload(utils_cursor)

import bpy
import bgl
import blf
import bmesh

from mathutils import Vector, Matrix, Quaternion, Euler

from mathutils.geometry import (intersect_line_sphere,
                                intersect_ray_tri,
                                barycentric_transform,
                                tessellate_polygon,
                                intersect_line_line,
                                intersect_line_plane,
                                )

from bpy_extras.view3d_utils import (region_2d_to_location_3d,
                                     location_3d_to_region_2d,
                                     )

import math
import time

try:
    import dairin0d
    dairin0d_location = ""
except ImportError:
    dairin0d_location = "."

exec("""
from {0}dairin0d.utils_math import *
from {0}dairin0d.utils_ui import NestedLayout, tag_redraw
from {0}dairin0d.utils_view3d import SmartView3D
from {0}dairin0d.utils_userinput import InputKeyMonitor, ModeStack, KeyMapUtils
from {0}dairin0d.bpy_inspect import prop, BlRna, BlEnums
from {0}dairin0d.utils_blender import ToggleObjectMode, MeshCache
from {0}dairin0d.utils_addon import AddonManager
""".format(dairin0d_location))

from .utils_cursor import *

addon = AddonManager()

#============================================================================#

"""
Bugs:
* tooltips don't appear (anywhere) if keymap auto-registration is enabled



Breakdown:
    Addon registration
    Keymap utils
    Various utils (e.g. find_region)
    OpenGL; drawing utils
    Non-undoable data storage
    Cursor utils
    Stick-object
    Cursor monitor
    Addon's GUI
    Addon's properties
    Addon's operators
    ID Block emulator
    Mesh cache
    Snap utils
    View3D utils
    Transform orientation / coordinate system utils
    Generic transform utils
    Main operator
    ...
.

First step is to re-make the cursor addon (make something usable first).
CAD tools should be done without the hassle.

TODO:
    strip trailing space? (one of campbellbarton's commits did that)

    IDEAS:
        - implement 'GIMBAL' orientation (euler axes)
        - mini-Z-buffer in the vicinity of mouse coords (using raycasts)
        - an orientation that points towards cursor
          (from current selection to cursor)
        - user coordinate systems (using e.g. empties to store different
          systems; when user switches to such UCS, origin will be set to
          "cursor", cursor will be sticked to the empty, and a custom
          transform orientation will be aligned with the empty)
          - "Stick" transform orientation that is always aligned with the
            object cursor is "sticked" to?
        - make 'NORMAL' system also work for bones?
        - user preferences? (stored in a file)
        - create spline/edge_mesh from history?
        - API to access history/bookmarks/operators from other scripts?
        - Snap selection to bookmark?
        - Optimize
        - Clean up code, move to several files?
    LATER:
    ISSUES:
        Limitations:
            - I need to emulate in Python some things that Blender doesn't
              currently expose through API:
              - obtaining matrix of predefined transform orientation
              - obtaining position of pivot
              For some kinds of information (e.g. active vertex/edge,
              selected meta-elements), there is simply no workaround.
            - Snapping to vertices/edges works differently than in Blender.
              First of all, iteration over all vertices/edges of all
              objects along the ray is likely to be very slow.
              Second, it's more human-friendly to snap to visible
              elements (or at least with approximately known position).
            - In editmode I have to exit-and-enter it to get relevant
              information about current selection. Thus any operator
              would automatically get applied when you click on 3D View.
        Mites:
    QUESTIONS:
==============================================================================
Borrowed code/logic:
- space_view3d_panel_measure.py (Buerbaum Martin "Pontiac"):
  - OpenGL state storing/restoring; working with projection matrices.
"""


# ====== SET CURSOR OPERATOR ====== #
@addon.Operator(idname="view3d.cursor3d_enhanced", label="Enhanced Set Cursor", description="Cursor history and bookmarks; drag/snap cursor.")
class EnhancedSetCursor(bpy.types.Operator):
    key_char_map = {
        'PERIOD':".", 'NUMPAD_PERIOD':".",
        'MINUS':"-", 'NUMPAD_MINUS':"-",
        'EQUAL':"+", 'NUMPAD_PLUS':"+",
        #'E':"e", # such big/small numbers aren't useful
        'ONE':"1", 'NUMPAD_1':"1",
        'TWO':"2", 'NUMPAD_2':"2",
        'THREE':"3", 'NUMPAD_3':"3",
        'FOUR':"4", 'NUMPAD_4':"4",
        'FIVE':"5", 'NUMPAD_5':"5",
        'SIX':"6", 'NUMPAD_6':"6",
        'SEVEN':"7", 'NUMPAD_7':"7",
        'EIGHT':"8", 'NUMPAD_8':"8",
        'NINE':"9", 'NUMPAD_9':"9",
        'ZERO':"0", 'NUMPAD_0':"0",
        'SPACE':" ",
        'SLASH':"/", 'NUMPAD_SLASH':"/",
        'NUMPAD_ASTERIX':"*",
    }

    key_coordsys_map = {
        'LEFT_BRACKET':-1,
        'RIGHT_BRACKET':1,
        'J':'VIEW',
        'K':"Surface",
        'L':'LOCAL',
        'B':'GLOBAL',
        'N':'NORMAL',
        'M':"Scaled",
    }

    key_pivot_map = {
        'H':'ACTIVE',
        'U':'CURSOR',
        'I':'INDIVIDUAL',
        'O':'CENTER',
        'P':'MEDIAN',
    }

    key_snap_map = {
        'C':'INCREMENT',
        'V':'VERTEX',
        'E':'EDGE',
        'F':'FACE',
    }

    key_tfm_mode_map = {
        'G':'MOVE',
        'R':'ROTATE',
        'S':'SCALE',
    }

    key_map = {
        "confirm":{'ACTIONMOUSE'}, # also 'RET' ?
        "cancel":{'SELECTMOUSE', 'ESC'},
        "free_mouse":{'F10'},
        "make_normal_snapshot":{'W'},
        "make_tangential_snapshot":{'Q'},
        "use_absolute_coords":{'A'},
        "snap_to_raw_mesh":{'D'},
        "use_object_centers":{'T'},
        "precision_up":{'PAGE_UP'},
        "precision_down":{'PAGE_DOWN'},
        "move_caret_prev":{'LEFT_ARROW'},
        "move_caret_next":{'RIGHT_ARROW'},
        "move_caret_home":{'HOME'},
        "move_caret_end":{'END'},
        "change_current_axis":{'TAB', 'RET', 'NUMPAD_ENTER'},
        "prev_axis":{'UP_ARROW'},
        "next_axis":{'DOWN_ARROW'},
        "remove_next_character":{'DEL'},
        "remove_last_character":{'BACK_SPACE'},
        "copy_axes":{'C'},
        "paste_axes":{'V'},
        "cut_axes":{'X'},
    }

    gizmo_factor = 0.15
    click_period = 0.25

    angle_grid_steps = {True:1.0, False:5.0}
    scale_grid_steps = {True:0.01, False:0.1}

    # ====== OPERATOR METHOD OVERLOADS ====== #
    @classmethod
    def poll(cls, context):
        area_types = {'VIEW_3D',} # also: IMAGE_EDITOR ?
        return (context.area.type in area_types) and (context.region.type == "WINDOW")

    def modal(self, context, event):
        context.area.tag_redraw()
        return self.try_process_input(context, event)

    def invoke(self, context, event):
        # Attempt to launch the monitor
        if bpy.ops.view3d.cursor3d_monitor.poll():
            bpy.ops.view3d.cursor3d_monitor()

        # Don't interfere with these modes when only mouse is pressed
        if ('SCULPT' in context.mode) or ('PAINT' in context.mode):
            if "MOUSE" in event.type:
                return {'CANCELLED'}

        CursorDynamicSettings.active_transform_operator = self

        tool_settings = context.tool_settings

        settings = find_settings()
        tfm_opts = settings.transform_options

        settings_scene = context.scene.cursor_3d_tools_settings

        self.setup_keymaps(context, event)

        # Coordinate System Utility
        self.particles, self.csu = gather_particles(context=context)
        self.particles = [View3D_Cursor(context)]

        self.csu.source_pos = self.particles[0].get_location()
        self.csu.source_rot = self.particles[0].get_rotation()
        self.csu.source_scale = self.particles[0].get_scale()

        # View3D Utility
        self.vu = ViewUtility(context.region, context.space_data,
            context.region_data)

        # Snap Utility
        self.su = SnapUtility(context)

        # turn off view locking for the duration of the operator
        self.view_pos = self.vu.get_position(True)
        self.vu.set_position(self.vu.get_position(), True)
        self.view_locks = self.vu.get_locks()
        self.vu.set_locks({})

        # Initialize runtime states
        self.initiated_by_mouse = ("MOUSE" in event.type)
        self.free_mouse = not self.initiated_by_mouse
        self.use_object_centers = False
        self.axes_values = ["", "", ""]
        self.axes_coords = [None, None, None]
        self.axes_eval_success = [True, True, True]
        self.allowed_axes = [True, True, True]
        self.current_axis = 0
        self.caret_pos = 0
        self.coord_format = "{:." + str(settings.free_coord_precision) + "f}"
        self.transform_mode = 'MOVE'
        self.init_xy_angle_distance(context, event)

        self.click_start = time.time()
        if not self.initiated_by_mouse:
            self.click_start -= self.click_period

        self.stick_obj_name = settings_scene.stick_obj_name
        self.stick_obj_pos = settings_scene.stick_obj_pos

        # Initial run
        self.try_process_input(context, event, True)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        for particle in self.particles:
            particle.revert()

        set_stick_obj(context.scene, self.stick_obj_name, self.stick_obj_pos)

        self.finalize(context)

    # ====== CLEANUP/FINALIZE ====== #
    def finalize(self, context):
        # restore view locking
        self.vu.set_locks(self.view_locks)
        self.vu.set_position(self.view_pos, True)

        self.cleanup(context)

        # This is to avoid "blinking" of
        # between-history-positions line
        settings = find_settings()
        history = settings.history
        # make sure the most recent history entry is displayed
        history.curr_id = 0
        history.last_id = 0

        # Ensure there are no leftovers from draw_callback
        context.area.tag_redraw()

        return {'FINISHED'}

    def cleanup(self, context):
        self.particles = None
        self.csu = None
        self.vu = None
        if self.su is not None:
            self.su.dispose()
        self.su = None

        CursorDynamicSettings.active_transform_operator = None

    # ====== USER INPUT PROCESSING ====== #
    def setup_keymaps(self, context, event=None):
        self.key_map = self.key_map.copy()

        # There is no such event as 'ACTIONMOUSE',
        # it's always 'LEFTMOUSE' or 'RIGHTMOUSE'
        if event:
            if event.type == 'LEFTMOUSE':
                self.key_map["confirm"] = {'LEFTMOUSE'}
                self.key_map["cancel"] = {'RIGHTMOUSE', 'ESC'}
            elif event.type == 'RIGHTMOUSE':
                self.key_map["confirm"] = {'RIGHTMOUSE'}
                self.key_map["cancel"] = {'LEFTMOUSE', 'ESC'}
            else:
                event = None
        if event is None:
            select_mouse = context.user_preferences.inputs.select_mouse
            if select_mouse == 'RIGHT':
                self.key_map["confirm"] = {'LEFTMOUSE'}
                self.key_map["cancel"] = {'RIGHTMOUSE', 'ESC'}
            else:
                self.key_map["confirm"] = {'RIGHTMOUSE'}
                self.key_map["cancel"] = {'LEFTMOUSE', 'ESC'}

        # Use user-defined "free mouse" key, if it exists
        wm = context.window_manager
        if '3D View' in wm.keyconfigs.user.keymaps:
            km = wm.keyconfigs.user.keymaps['3D View']
            for kmi in KeyMapItemSearch(EnhancedSetCursor.bl_idname, km):
                if kmi.map_type == 'KEYBOARD':
                    self.key_map["free_mouse"] = {kmi.type,}
                    break

    def try_process_input(self, context, event, initial_run=False):
        try:
            return self.process_input(context, event, initial_run)
        except:
            # If anything fails, at least dispose the resources
            self.cleanup(context)
            raise

    def process_input(self, context, event, initial_run=False):
        wm = context.window_manager
        v3d = context.space_data

        if event.type in self.key_map["confirm"]:
            if self.free_mouse:
                finished = (event.value == 'PRESS')
            else:
                finished = (event.value == 'RELEASE')

            if finished:
                return self.finalize(context)

        if event.type in self.key_map["cancel"]:
            self.cancel(context)
            return {'CANCELLED'}

        tool_settings = context.tool_settings

        settings = find_settings()
        tfm_opts = settings.transform_options

        make_snapshot = False
        tangential_snapshot = False

        if event.value == 'PRESS':
            if event.type in self.key_map["free_mouse"]:
                if self.free_mouse and not initial_run:
                    # confirm if pressed second time
                    return self.finalize(context)
                else:
                    self.free_mouse = True

            if event.type in self.key_tfm_mode_map:
                new_mode = self.key_tfm_mode_map[event.type]

                if self.transform_mode != new_mode:
                    # snap cursor to its initial state
                    if new_mode != 'MOVE':
                        for particle in self.particles:
                            initial_matrix = particle.get_initial_matrix()
                            particle.set_matrix(initial_matrix)
                    # reset intial mouse position
                    self.init_xy_angle_distance(context, event)

                self.transform_mode = new_mode

            if event.type in self.key_map["make_normal_snapshot"]:
                make_snapshot = True
                tangential_snapshot = False

            if event.type in self.key_map["make_tangential_snapshot"]:
                make_snapshot = True
                tangential_snapshot = True

            if event.type in self.key_map["snap_to_raw_mesh"]:
                tool_settings.use_snap_self = \
                    not tool_settings.use_snap_self

            if (not event.alt) and (event.type in {'X', 'Y', 'Z'}):
                axis_lock = [(event.type == 'X') != event.shift,
                             (event.type == 'Y') != event.shift,
                             (event.type == 'Z') != event.shift]

                if self.allowed_axes != axis_lock:
                    self.allowed_axes = axis_lock
                else:
                    self.allowed_axes = [True, True, True]

            if event.type in self.key_map["use_absolute_coords"]:
                tfm_opts.use_relative_coords = \
                    not tfm_opts.use_relative_coords

                self.update_origin_projection(context)

            incr = 0
            if event.type in self.key_map["change_current_axis"]:
                incr = (-1 if event.shift else 1)
            elif event.type in self.key_map["next_axis"]:
                incr = 1
            elif event.type in self.key_map["prev_axis"]:
                incr = -1

            if incr != 0:
                self.current_axis = (self.current_axis + incr) % 3
                self.caret_pos = len(self.axes_values[self.current_axis])

            incr = 0
            if event.type in self.key_map["precision_up"]:
                incr = 1
            elif event.type in self.key_map["precision_down"]:
                incr = -1

            if incr != 0:
                settings.free_coord_precision += incr
                self.coord_format = "{:." + \
                    str(settings.free_coord_precision) + "f}"

            if (event.type == 'ZERO') and event.ctrl:
                self.snap_to_system_origin()
            else:
                self.process_axis_input(event)

            if event.alt:
                jc = (", " if tfm_opts.use_comma_separator else "\t")
                if event.type in self.key_map["copy_axes"]:
                    wm.clipboard = jc.join(self.get_axes_text(True))
                elif event.type in self.key_map["cut_axes"]:
                    wm.clipboard = jc.join(self.get_axes_text(True))
                    self.set_axes_text("\t\t\t")
                elif event.type in self.key_map["paste_axes"]:
                    if jc == "\t":
                        self.set_axes_text(wm.clipboard, True)
                    else:
                        jc = jc.strip()
                        ttext = ""
                        brackets = 0
                        for c in wm.clipboard:
                            if c in "[{(":
                                brackets += 1
                            elif c in "]})":
                                brackets -= 1
                            if (brackets == 0) and (c == jc):
                                c = "\t"
                            ttext += c
                        self.set_axes_text(ttext, True)

            if event.type in self.key_coordsys_map:
                new_orientation = self.key_coordsys_map[event.type]
                self.csu.set_orientation(new_orientation)

                self.update_origin_projection(context)

                if event.ctrl:
                    self.snap_to_system_origin()

            if event.type in self.key_map["use_object_centers"]:
                v3d.use_pivot_point_align = not v3d.use_pivot_point_align

            if event.type in self.key_pivot_map:
                self.csu.set_pivot(self.key_pivot_map[event.type])

                self.update_origin_projection(context)

                if event.ctrl:
                    self.snap_to_system_origin(force_pivot=True)

            if (not event.alt) and (event.type in self.key_snap_map):
                snap_element = self.key_snap_map[event.type]
                if tool_settings.snap_element == snap_element:
                    if snap_element == 'VERTEX':
                        snap_element = 'VOLUME'
                    elif snap_element == 'VOLUME':
                        snap_element = 'VERTEX'
                tool_settings.snap_element = snap_element
        # end if

        use_snap = (tool_settings.use_snap != event.ctrl)
        if use_snap:
            snap_type = tool_settings.snap_element
        else:
            userprefs_view = context.user_preferences.view
            if userprefs_view.use_mouse_depth_cursor:
                # Suggested by Lissanro in the forum
                use_snap = True
                snap_type = 'FACE'
            else:
                snap_type = None

        axes_coords = [None, None, None]
        if self.transform_mode == 'MOVE':
            for i in range(3):
                if self.axes_coords[i] is not None:
                    axes_coords[i] = self.axes_coords[i]
                elif not self.allowed_axes[i]:
                    axes_coords[i] = 0.0

        self.su.set_modes(
            interpolation=tfm_opts.snap_interpolate_normals_mode,
            use_relative_coords=tfm_opts.use_relative_coords,
            editmode=tool_settings.use_snap_self,
            snap_type=snap_type,
            snap_align=tool_settings.use_snap_align_rotation,
            axes_coords=axes_coords,
            )

        self.do_raycast = ("MOUSE" in event.type)
        self.grid_substep = event.shift
        self.modify_surface_orientation = (len(self.particles) == 1)
        self.xy = Vector((event.mouse_region_x, event.mouse_region_y))

        self.use_object_centers = v3d.use_pivot_point_align

        if event.type == 'MOUSEMOVE':
            self.update_transform_mousemove()

        if self.transform_mode == 'MOVE':
            transform_func = self.transform_move
        elif self.transform_mode == 'ROTATE':
            transform_func = self.transform_rotate
        elif self.transform_mode == 'SCALE':
            transform_func = self.transform_scale

        for particle in self.particles:
            transform_func(particle)

        if make_snapshot:
            self.make_normal_snapshot(context.scene, tangential_snapshot)

        return {'RUNNING_MODAL'}

    def update_origin_projection(self, context):
        r = context.region
        rv3d = context.region_data

        origin = self.csu.get_origin()
        # prehaps not projection, but intersection with plane?
        self.origin_xy = location_3d_to_region_2d(r, rv3d, origin)
        if self.origin_xy is None:
            self.origin_xy = Vector((r.width / 2, r.height / 2))

        self.delta_xy = (self.start_xy - self.origin_xy).to_3d()
        self.prev_delta_xy = self.delta_xy

    def init_xy_angle_distance(self, context, event):
        self.start_xy = Vector((event.mouse_region_x, event.mouse_region_y))

        self.update_origin_projection(context)

        # Distinction between angles has to be made because
        # angles can go beyond 360 degrees (we cannot snap
        # to increment the original ones).
        self.raw_angles = [0.0, 0.0, 0.0]
        self.angles = [0.0, 0.0, 0.0]
        self.scales = [1.0, 1.0, 1.0]

    def update_transform_mousemove(self):
        delta_xy = (self.xy - self.origin_xy).to_3d()

        n_axes = sum(int(v) for v in self.allowed_axes)
        if n_axes == 1:
            # rotate using angle as value
            rd = self.prev_delta_xy.rotation_difference(delta_xy)
            offset = -rd.angle * round(rd.axis[2])

            sys_matrix = self.csu.get_matrix()

            i_allowed = 0
            for i in range(3):
                if self.allowed_axes[i]:
                    i_allowed = i

            view_dir = self.vu.get_direction()
            if view_dir.dot(sys_matrix[i_allowed][:3]) < 0:
                offset = -offset

            for i in range(3):
                if self.allowed_axes[i]:
                    self.raw_angles[i] += offset
        elif n_axes == 2:
            # rotate using XY coords as two values
            offset = (delta_xy - self.prev_delta_xy) * (math.pi / 180.0)

            if self.grid_substep:
                offset *= 0.1
            else:
                offset *= 0.5

            j = 0
            for i in range(3):
                if self.allowed_axes[i]:
                    self.raw_angles[i] += offset[1 - j]
                    j += 1
        elif n_axes == 3:
            # rotate around view direction
            rd = self.prev_delta_xy.rotation_difference(delta_xy)
            offset = -rd.angle * round(rd.axis[2])

            view_dir = self.vu.get_direction()

            sys_matrix = self.csu.get_matrix()

            try:
                view_dir = sys_matrix.inverted().to_3x3() * view_dir
            except:
                # this is some degenerate system
                pass
            view_dir.normalize()

            rot = Matrix.Rotation(offset, 3, view_dir)

            matrix = Euler(self.raw_angles, 'XYZ').to_matrix()
            matrix.rotate(rot)

            euler = matrix.to_euler('XYZ')
            self.raw_angles[0] += clamp_angle(euler.x - self.raw_angles[0])
            self.raw_angles[1] += clamp_angle(euler.y - self.raw_angles[1])
            self.raw_angles[2] += clamp_angle(euler.z - self.raw_angles[2])

        scale = delta_xy.length / self.delta_xy.length
        if self.delta_xy.dot(delta_xy) < 0:
            scale *= -1
        for i in range(3):
            if self.allowed_axes[i]:
                self.scales[i] = scale

        self.prev_delta_xy = delta_xy

    def transform_move(self, particle):
        global set_cursor_location__reset_stick

        src_matrix = particle.get_matrix()
        initial_matrix = particle.get_initial_matrix()

        matrix = self.su.snap(
            self.xy, src_matrix, initial_matrix,
            self.do_raycast, self.grid_substep,
            self.vu, self.csu,
            self.modify_surface_orientation,
            self.use_object_centers)

        set_cursor_location__reset_stick = False
        particle.set_matrix(matrix)
        set_cursor_location__reset_stick = True

    def rotate_matrix(self, matrix):
        sys_matrix = self.csu.get_matrix()

        try:
            matrix = sys_matrix.inverted() * matrix
        except:
            # this is some degenerate system
            pass

        # Blender's order of rotation [in local axes]
        rotation_order = [2, 1, 0]

        # Seems that 4x4 matrix cannot be rotated using rotate() ?
        sys_matrix3 = sys_matrix.to_3x3()

        for i in range(3):
            j = rotation_order[i]
            axis = sys_matrix3[j]
            angle = self.angles[j]

            rot = angle_axis_to_quat(angle, axis)
            # this seems to be buggy too
            #rot = Matrix.Rotation(angle, 3, axis)

            sys_matrix3 = rot.to_matrix() * sys_matrix3
            # sys_matrix3.rotate has a bug? or I don't understand how it works?
            #sys_matrix3.rotate(rot)

        for i in range(3):
            sys_matrix[i][:3] = sys_matrix3[i]

        matrix = sys_matrix * matrix

        return matrix

    def transform_rotate(self, particle):
        grid_step = self.angle_grid_steps[self.grid_substep]
        grid_step *= (math.pi / 180.0)

        for i in range(3):
            if self.axes_values[i] and self.axes_eval_success[i]:
                self.raw_angles[i] = self.axes_coords[i] * (math.pi / 180.0)

            self.angles[i] = self.raw_angles[i]

        if self.su.implementation.snap_type == 'INCREMENT':
            for i in range(3):
                self.angles[i] = round_step(self.angles[i], grid_step)

        initial_matrix = particle.get_initial_matrix()
        matrix = self.rotate_matrix(initial_matrix)

        particle.set_matrix(matrix)

    def scale_matrix(self, matrix):
        sys_matrix = self.csu.get_matrix()

        try:
            matrix = sys_matrix.inverted() * matrix
        except:
            # this is some degenerate system
            pass

        for i in range(3):
            sys_matrix[i] *= self.scales[i]

        matrix = sys_matrix * matrix

        return matrix

    def transform_scale(self, particle):
        grid_step = self.scale_grid_steps[self.grid_substep]

        for i in range(3):
            if self.axes_values[i] and self.axes_eval_success[i]:
                self.scales[i] = self.axes_coords[i]

        if self.su.implementation.snap_type == 'INCREMENT':
            for i in range(3):
                self.scales[i] = round_step(self.scales[i], grid_step)

        initial_matrix = particle.get_initial_matrix()
        matrix = self.scale_matrix(initial_matrix)

        particle.set_matrix(matrix)

    def set_axis_input(self, axis_id, axis_val):
        if axis_val == self.axes_values[axis_id]:
            return

        self.axes_values[axis_id] = axis_val

        if len(axis_val) == 0:
            self.axes_coords[axis_id] = None
            self.axes_eval_success[axis_id] = True
        else:
            try:
                #self.axes_coords[axis_id] = float(eval(axis_val, {}, {}))
                self.axes_coords[axis_id] = \
                    float(eval(axis_val, math.__dict__))
                self.axes_eval_success[axis_id] = True
            except:
                self.axes_eval_success[axis_id] = False

    def snap_to_system_origin(self, force_pivot=False):
        if self.transform_mode == 'MOVE':
            pivot = self.csu.get_pivot_name(raw=force_pivot)
            p = self.csu.get_origin(relative=False, pivot=pivot)
            m = self.csu.get_matrix()
            try:
                p = m.inverted() * p
            except:
                # this is some degenerate system
                pass
            for i in range(3):
                self.set_axis_input(i, str(p[i]))
        elif self.transform_mode == 'ROTATE':
            for i in range(3):
                self.set_axis_input(i, "0")
        elif self.transform_mode == 'SCALE':
            for i in range(3):
                self.set_axis_input(i, "1")

    def get_axes_values(self, as_string=False):
        if self.transform_mode == 'MOVE':
            localmat = CursorDynamicSettings.local_matrix
            raw_axes = localmat.translation
        elif self.transform_mode == 'ROTATE':
            raw_axes = Vector(self.angles) * (180.0 / math.pi)
        elif self.transform_mode == 'SCALE':
            raw_axes = Vector(self.scales)

        axes_values = []
        for i in range(3):
            if as_string and self.axes_values[i]:
                value = self.axes_values[i]
            elif self.axes_eval_success[i] and \
                    (self.axes_coords[i] is not None):
                value = self.axes_coords[i]
            else:
                value = raw_axes[i]
                if as_string:
                    value = self.coord_format.format(value)
            axes_values.append(value)

        return axes_values

    def get_axes_text(self, offset=False):
        axes_values = self.get_axes_values(as_string=True)

        axes_text = []
        for i in range(3):
            j = i
            if offset:
                j = (i + self.current_axis) % 3

            axes_text.append(axes_values[j])

        return axes_text

    def set_axes_text(self, text, offset=False):
        if "\n" in text:
            text = text.replace("\r", "")
        else:
            text = text.replace("\r", "\n")
        text = text.replace("\n", "\t")
        #text = text.replace(",", ".") # ???

        axes_text = text.split("\t")
        for i in range(min(len(axes_text), 3)):
            j = i
            if offset:
                j = (i + self.current_axis) % 3
            self.set_axis_input(j, axes_text[i])

    def process_axis_input(self, event):
        axis_id = self.current_axis
        axis_val = self.axes_values[axis_id]

        if event.type in self.key_map["remove_next_character"]:
            if event.ctrl:
                # clear all
                for i in range(3):
                    self.set_axis_input(i, "")
                self.caret_pos = 0
                return
            else:
                axis_val = axis_val[0:self.caret_pos] + \
                           axis_val[self.caret_pos + 1:len(axis_val)]
        elif event.type in self.key_map["remove_last_character"]:
            if event.ctrl:
                # clear current
                axis_val = ""
            else:
                axis_val = axis_val[0:self.caret_pos - 1] + \
                           axis_val[self.caret_pos:len(axis_val)]
                self.caret_pos -= 1
        elif event.type in self.key_map["move_caret_next"]:
            self.caret_pos += 1
            if event.ctrl:
                snap_chars = ".-+*/%()"
                i = self.caret_pos
                while axis_val[i:i + 1] not in snap_chars:
                    i += 1
                self.caret_pos = i
        elif event.type in self.key_map["move_caret_prev"]:
            self.caret_pos -= 1
            if event.ctrl:
                snap_chars = ".-+*/%()"
                i = self.caret_pos
                while axis_val[i - 1:i] not in snap_chars:
                    i -= 1
                self.caret_pos = i
        elif event.type in self.key_map["move_caret_home"]:
            self.caret_pos = 0
        elif event.type in self.key_map["move_caret_end"]:
            self.caret_pos = len(axis_val)
        elif event.type in self.key_char_map:
            # Currently accessing event.ascii seems to crash Blender
            c = self.key_char_map[event.type]
            if event.shift:
                if c == "8":
                    c = "*"
                elif c == "5":
                    c = "%"
                elif c == "9":
                    c = "("
                elif c == "0":
                    c = ")"
            axis_val = axis_val[0:self.caret_pos] + c + \
                       axis_val[self.caret_pos:len(axis_val)]
            self.caret_pos += 1

        self.caret_pos = min(max(self.caret_pos, 0), len(axis_val))

        self.set_axis_input(axis_id, axis_val)

    # ====== DRAWING ====== #
    def gizmo_distance(self, pos):
        rv3d = self.vu.region_data
        if rv3d.view_perspective == 'ORTHO':
            dist = rv3d.view_distance
        else:
            view_pos = self.vu.get_viewpoint()
            view_dir = self.vu.get_direction()
            dist = (pos - view_pos).dot(view_dir)
        return dist

    def gizmo_scale(self, pos):
        return self.gizmo_distance(pos) * self.gizmo_factor

    def check_v3d_local(self, context):
        csu_v3d = self.csu.space_data
        v3d = context.space_data
        if csu_v3d.local_view:
            return csu_v3d != v3d
        return v3d.local_view

    def draw_3d(self, context):
        if self.check_v3d_local(context):
            return

        if time.time() < (self.click_start + self.click_period):
            return

        settings = find_settings()
        tfm_opts = settings.transform_options

        initial_matrix = self.particles[0].get_initial_matrix()

        sys_matrix = self.csu.get_matrix()
        if tfm_opts.use_relative_coords:
            sys_matrix.translation = initial_matrix.translation.copy()
        sys_origin = sys_matrix.to_translation()
        dest_point = self.particles[0].get_location()

        if self.is_normal_visible():
            p0, x, y, z, _x, _z = \
                self.get_normal_params(tfm_opts, dest_point)

            # use theme colors?
            #ThemeView3D.normal
            #ThemeView3D.vertex_normal

            bgl.glDisable(bgl.GL_LINE_STIPPLE)

            if settings.draw_N:
                bgl.glColor4f(0, 1, 1, 1)
                draw_arrow(p0, _x, y, z) # Z (normal)
            if settings.draw_T1:
                bgl.glColor4f(1, 0, 1, 1)
                draw_arrow(p0, y, _z, x) # X (1st tangential)
            if settings.draw_T2:
                bgl.glColor4f(1, 1, 0, 1)
                draw_arrow(p0, _z, x, y) # Y (2nd tangential)

            bgl.glEnable(bgl.GL_BLEND)
            bgl.glDisable(bgl.GL_DEPTH_TEST)

            if settings.draw_N:
                bgl.glColor4f(0, 1, 1, 0.25)
                draw_arrow(p0, _x, y, z) # Z (normal)
            if settings.draw_T1:
                bgl.glColor4f(1, 0, 1, 0.25)
                draw_arrow(p0, y, _z, x) # X (1st tangential)
            if settings.draw_T2:
                bgl.glColor4f(1, 1, 0, 0.25)
                draw_arrow(p0, _z, x, y) # Y (2nd tangential)

        if settings.draw_guides:
            p0 = dest_point
            try:
                p00 = sys_matrix.inverted() * p0
            except:
                # this is some degenerate system
                p00 = p0.copy()

            axes_line_params = [
                (Vector((0, p00.y, p00.z)), (1, 0, 0)),
                (Vector((p00.x, 0, p00.z)), (0, 1, 0)),
                (Vector((p00.x, p00.y, 0)), (0, 0, 1)),
            ]

            for i in range(3):
                p1, color = axes_line_params[i]
                p1 = sys_matrix * p1
                constrained = (self.axes_coords[i] is not None) or \
                    (not self.allowed_axes[i])
                alpha = (0.25 if constrained else 1.0)
                draw_line_hidden_depth(p0, p1, color, \
                    alpha, alpha, False, True)

            # line from origin to cursor
            p0 = sys_origin
            p1 = dest_point

            bgl.glEnable(bgl.GL_LINE_STIPPLE)
            bgl.glColor4f(1, 1, 0, 1)

            draw_line_hidden_depth(p0, p1, (1, 1, 0), 1.0, 0.5, True, True)

        if settings.draw_snap_elements:
            sui = self.su.implementation
            if sui.potential_snap_elements and (sui.snap_type == 'EDGE'):
                bgl.glDisable(bgl.GL_LINE_STIPPLE)

                bgl.glEnable(bgl.GL_BLEND)
                bgl.glDisable(bgl.GL_DEPTH_TEST)

                bgl.glLineWidth(2)
                bgl.glColor4f(0, 0, 1, 0.5)

                bgl.glBegin(bgl.GL_LINE_LOOP)
                for p in sui.potential_snap_elements:
                    bgl.glVertex3f(p[0], p[1], p[2])
                bgl.glEnd()
            elif sui.potential_snap_elements and (sui.snap_type == 'FACE'):
                bgl.glEnable(bgl.GL_BLEND)
                bgl.glDisable(bgl.GL_DEPTH_TEST)

                bgl.glColor4f(0, 1, 0, 0.5)

                co = sui.potential_snap_elements
                tris = tessellate_polygon([co])
                bgl.glBegin(bgl.GL_TRIANGLES)
                for tri in tris:
                    for vi in tri:
                        p = co[vi]
                        bgl.glVertex3f(p[0], p[1], p[2])
                bgl.glEnd()

    def draw_2d(self, context):
        if self.check_v3d_local(context):
            return

        r = context.region
        rv3d = context.region_data

        settings = find_settings()

        if settings.draw_snap_elements:
            sui = self.su.implementation

            snap_points = []
            if sui.potential_snap_elements and \
                    (sui.snap_type in {'VERTEX', 'VOLUME'}):
                snap_points.extend(sui.potential_snap_elements)
            if sui.extra_snap_points:
                snap_points.extend(sui.extra_snap_points)

            if snap_points:
                bgl.glEnable(bgl.GL_BLEND)

                bgl.glPointSize(5)
                bgl.glColor4f(1, 0, 0, 0.5)

                bgl.glBegin(bgl.GL_POINTS)
                for p in snap_points:
                    p = location_3d_to_region_2d(r, rv3d, p)
                    if p is not None:
                        bgl.glVertex2f(p[0], p[1])
                bgl.glEnd()

                bgl.glPointSize(1)

        if self.transform_mode == 'MOVE':
            return

        bgl.glEnable(bgl.GL_LINE_STIPPLE)

        bgl.glLineWidth(1)

        bgl.glColor4f(0, 0, 0, 1)
        draw_line_2d(self.origin_xy, self.xy)

        bgl.glDisable(bgl.GL_LINE_STIPPLE)

        line_width = 3
        bgl.glLineWidth(line_width)

        L = 12.0
        arrow_len = 6.0
        arrow_width = 8.0
        arrow_space = 5.0

        Lmax = arrow_space * 2 + L * 2 + line_width

        pos = self.xy.to_2d()
        normal = self.prev_delta_xy.to_2d().normalized()
        dist = self.prev_delta_xy.length
        tangential = Vector((-normal[1], normal[0]))

        if self.transform_mode == 'ROTATE':
            n_axes = sum(int(v) for v in self.allowed_axes)
            if n_axes == 2:
                bgl.glColor4f(0.4, 0.15, 0.15, 1)
                for sgn in (-1, 1):
                    n = sgn * Vector((0, 1))
                    p0 = pos + arrow_space * n
                    draw_arrow_2d(p0, n, L, arrow_len, arrow_width)

                bgl.glColor4f(0.11, 0.51, 0.11, 1)
                for sgn in (-1, 1):
                    n = sgn * Vector((1, 0))
                    p0 = pos + arrow_space * n
                    draw_arrow_2d(p0, n, L, arrow_len, arrow_width)
            else:
                bgl.glColor4f(0, 0, 0, 1)
                for sgn in (-1, 1):
                    n = sgn * tangential
                    if dist < Lmax:
                        n *= dist / Lmax
                    p0 = pos + arrow_space * n
                    draw_arrow_2d(p0, n, L, arrow_len, arrow_width)
        elif self.transform_mode == 'SCALE':
            bgl.glColor4f(0, 0, 0, 1)
            for sgn in (-1, 1):
                n = sgn * normal
                p0 = pos + arrow_space * n
                draw_arrow_2d(p0, n, L, arrow_len, arrow_width)

        bgl.glLineWidth(1)

    def draw_axes_coords(self, context, header_size):
        if self.check_v3d_local(context):
            return

        if time.time() < (self.click_start + self.click_period):
            return

        v3d = context.space_data

        userprefs_view = context.user_preferences.view

        tool_settings = context.tool_settings

        settings = find_settings()
        tfm_opts = settings.transform_options

        localmat = CursorDynamicSettings.local_matrix

        font_id = 0 # default font

        font_size = 11
        blf.size(font_id, font_size, 72) # font, point size, dpi

        tet = context.user_preferences.themes[0].text_editor

        # Prepare the table...
        if self.transform_mode == 'MOVE':
            axis_prefix = ("D" if tfm_opts.use_relative_coords else "")
        elif self.transform_mode == 'SCALE':
            axis_prefix = "S"
        else:
            axis_prefix = "R"
        axis_names = ["X", "Y", "Z"]

        axis_cells = []
        coord_cells = []
        #caret_cell = TextCell("_", tet.cursor)
        caret_cell = TextCell("|", tet.cursor)

        try:
            axes_text = self.get_axes_text()

            for i in range(3):
                color = tet.space.text
                alpha = (1.0 if self.allowed_axes[i] else 0.5)
                text = axis_prefix + axis_names[i] + " : "
                axis_cells.append(TextCell(text, color, alpha))

                if self.axes_values[i]:
                    if self.axes_eval_success[i]:
                        color = tet.syntax_numbers
                    else:
                        color = tet.syntax_string
                else:
                    color = tet.space.text
                text = axes_text[i]
                coord_cells.append(TextCell(text, color))
        except Exception as e:
            print(repr(e))

        mode_cells = []

        try:
            snap_type = self.su.implementation.snap_type
            if snap_type is None:
                color = tet.space.text
            elif (not self.use_object_centers) or \
                    (snap_type == 'INCREMENT'):
                color = tet.syntax_numbers
            else:
                color = tet.syntax_special
            text = snap_type or tool_settings.snap_element
            if text == 'VOLUME':
                text = "BBOX"
            mode_cells.append(TextCell(text, color))

            if self.csu.tou.is_custom:
                color = tet.space.text
            else:
                color = tet.syntax_builtin
            text = self.csu.tou.get_title()
            mode_cells.append(TextCell(text, color))

            color = tet.space.text
            text = self.csu.get_pivot_name(raw=True)
            if self.use_object_centers:
                color = tet.syntax_special
            mode_cells.append(TextCell(text, color))
        except Exception as e:
            print(repr(e))

        hdr_w, hdr_h = header_size

        try:
            xyz_x_start_min = 12
            xyz_x_start = xyz_x_start_min
            mode_x_start = 6

            mode_margin = 4
            xyz_margin = 16
            blend_margin = 32

            color = tet.space.back
            bgl.glColor4f(color[0], color[1], color[2], 1.0)
            draw_rect(0, 0, hdr_w, hdr_h)

            if tool_settings.use_snap_self:
                x = hdr_w - mode_x_start
                y = hdr_h / 2
                cell = mode_cells[0]
                x -= cell.w
                y -= cell.h * 0.5
                bgl.glColor4f(0.0, 0.0, 0.0, 1.0)
                draw_rect(x, y, cell.w, cell.h, 1, True)

            x = hdr_w - mode_x_start
            y = hdr_h / 2
            for cell in mode_cells:
                cell.draw(x, y, (1, 0.5))
                x -= (cell.w + mode_margin)

            curr_axis_x_start = 0
            curr_axis_x_end = 0
            caret_x = 0

            xyz_width = 0
            for i in range(3):
                if i == self.current_axis:
                    curr_axis_x_start = xyz_width

                xyz_width += axis_cells[i].w

                if i == self.current_axis:
                    char_offset = 0
                    if self.axes_values[i]:
                        char_offset = blf.dimensions(font_id,
                            coord_cells[i].text[:self.caret_pos])[0]
                    caret_x = xyz_width + char_offset

                xyz_width += coord_cells[i].w

                if i == self.current_axis:
                    curr_axis_x_end = xyz_width

                xyz_width += xyz_margin

            xyz_width = int(xyz_width)
            xyz_width_ext = xyz_width + blend_margin

            offset = (xyz_x_start + curr_axis_x_end) - hdr_w
            if offset > 0:
                xyz_x_start -= offset

            offset = xyz_x_start_min - (xyz_x_start + curr_axis_x_start)
            if offset > 0:
                xyz_x_start += offset

            offset = (xyz_x_start + caret_x) - hdr_w
            if offset > 0:
                xyz_x_start -= offset

            # somewhy GL_BLEND should be set right here
            # to actually draw the box with blending %)
            # (perhaps due to text draw happened before)
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glShadeModel(bgl.GL_SMOOTH)
            gl_enable(bgl.GL_SMOOTH, True)
            color = tet.space.back
            bgl.glBegin(bgl.GL_TRIANGLE_STRIP)
            bgl.glColor4f(color[0], color[1], color[2], 1.0)
            bgl.glVertex2i(0, 0)
            bgl.glVertex2i(0, hdr_h)
            bgl.glVertex2i(xyz_width, 0)
            bgl.glVertex2i(xyz_width, hdr_h)
            bgl.glColor4f(color[0], color[1], color[2], 0.0)
            bgl.glVertex2i(xyz_width_ext, 0)
            bgl.glVertex2i(xyz_width_ext, hdr_h)
            bgl.glEnd()

            x = xyz_x_start
            y = hdr_h / 2
            for i in range(3):
                cell = axis_cells[i]
                cell.draw(x, y, (0, 0.5))
                x += cell.w

                cell = coord_cells[i]
                cell.draw(x, y, (0, 0.5))
                x += (cell.w + xyz_margin)

            caret_x -= blf.dimensions(font_id, caret_cell.text)[0] * 0.5
            caret_cell.draw(xyz_x_start + caret_x, y, (0, 0.5))

            bgl.glEnable(bgl.GL_BLEND)
            bgl.glShadeModel(bgl.GL_SMOOTH)
            gl_enable(bgl.GL_SMOOTH, True)
            color = tet.space.back
            bgl.glBegin(bgl.GL_TRIANGLE_STRIP)
            bgl.glColor4f(color[0], color[1], color[2], 1.0)
            bgl.glVertex2i(0, 0)
            bgl.glVertex2i(0, hdr_h)
            bgl.glVertex2i(xyz_x_start_min, 0)
            bgl.glColor4f(color[0], color[1], color[2], 0.0)
            bgl.glVertex2i(xyz_x_start_min, hdr_h)
            bgl.glEnd()

        except Exception as e:
            print(repr(e))

        return

    # ====== NORMAL SNAPSHOT ====== #
    def is_normal_visible(self):
        if self.csu.tou.get() == "Surface":
            return True

        if self.use_object_centers:
            return False

        return self.su.implementation.snap_type \
            not in {None, 'INCREMENT', 'VOLUME'}

    def get_normal_params(self, tfm_opts, dest_point):
        surf_matrix = self.csu.get_matrix("Surface")
        if tfm_opts.use_relative_coords:
            surf_origin = dest_point
        else:
            surf_origin = surf_matrix.to_translation()

        m3 = surf_matrix.to_3x3()
        p0 = surf_origin
        scl = self.gizmo_scale(p0)

        # Normal and tangential are not always orthogonal
        # (e.g. when normal is interpolated)
        x = (m3 * Vector((1, 0, 0))).normalized()
        y = (m3 * Vector((0, 1, 0))).normalized()
        z = (m3 * Vector((0, 0, 1))).normalized()

        _x = z.cross(y)
        _z = y.cross(x)

        return p0, x * scl, y * scl, z * scl, _x * scl, _z * scl

    def make_normal_snapshot(self, scene, tangential=False):
        settings = find_settings()
        tfm_opts = settings.transform_options

        dest_point = self.particles[0].get_location()

        if self.is_normal_visible():
            p0, x, y, z, _x, _z = \
                self.get_normal_params(tfm_opts, dest_point)

            snapshot = bpy.data.objects.new("normal_snapshot", None)

            if tangential:
                m = matrix_compose(_z, y, x, p0)
            else:
                m = matrix_compose(_x, y, z, p0)
            snapshot.matrix_world = m

            snapshot.empty_draw_type = 'SINGLE_ARROW'
            #snapshot.empty_draw_type = 'ARROWS'
            #snapshot.layers = [True] * 20 # ?
            scene.objects.link(snapshot)
#============================================================================#






#============================================================================#
# ===== PANELS AND DIALOGS ===== #
@addon.Panel(idname="OBJECT_PT_transform_extra_options", space_type="VIEW_3D", region_type="UI", label="Transform Extra Options", options={'DEFAULT_CLOSED'})
class TransformExtraOptions:
    def draw(self, context):
        layout = self.layout

        settings = find_settings()
        tfm_opts = settings.transform_options

        layout.prop(tfm_opts, "use_relative_coords")
        layout.prop(tfm_opts, "snap_only_to_solid")
        layout.prop(tfm_opts, "snap_interpolate_normals_mode", text="")
        layout.prop(tfm_opts, "use_comma_separator")
        #layout.prop(tfm_opts, "snap_element_screen_size")

@addon.Panel(idname="OBJECT_PT_cursor_3d_tools", space_type="VIEW_3D", region_type="UI", label="3D Cursor Tools", options={'DEFAULT_CLOSED'})
class Cursor3DTools:
    def draw(self, context):
        layout = self.layout

        # Attempt to launch the monitor
        if bpy.ops.view3d.cursor3d_monitor.poll():
            bpy.ops.view3d.cursor3d_monitor()

        # If addon is enabled by default, the new scene
        # created on Blender startup will have disabled
        # standard Cursor3D behavior. However, if user
        # creates new scene, somehow Cursor3D is active
        # as if nothing happened xD
        update_keymap(True)
        #=============================================#

        settings = find_settings()

        row = layout.split(0.5)
        #row = layout.row()
        row.operator("view3d.set_cursor3d_dialog",
            "Set", 'CURSOR')
        row = row.split(1 / 3, align=True)
        #row = row.row(align=True)
        row.prop(settings, "draw_guides",
            text="", icon='MANIPUL', toggle=True)
        row.prop(settings, "draw_snap_elements",
            text="", icon='EDITMODE_HLT', toggle=True)
        row.prop(settings, "stick_to_obj",
            text="", icon='SNAP_ON', toggle=True)

        row = layout.row()
        row.label(text="Draw")
        '''
        row.prop(settings, "cursor_visible", text="", toggle=True,
                 icon=('RESTRICT_VIEW_OFF' if settings.cursor_visible
                       else 'RESTRICT_VIEW_ON'))
        #'''
        #'''
        subrow = row.row()
        #subrow.enabled = False
        subrow.alert = True
        subrow.prop(settings, "cursor_visible", text="", toggle=True,
                 icon=('RESTRICT_VIEW_OFF' if settings.cursor_visible
                       else 'RESTRICT_VIEW_ON'))
        #'''
        row = row.split(1 / 3, align=True)
        row.prop(settings, "draw_N",
            text="N", toggle=True, index=0)
        row.prop(settings, "draw_T1",
            text="T1", toggle=True, index=1)
        row.prop(settings, "draw_T2",
            text="T2", toggle=True, index=2)

        # === HISTORY === #
        history = settings.history
        row = layout.row(align=True)
        row.prop(history, "show_trace", text="", icon='SORTTIME')
        row = row.split(0.35, True)
        row.prop(history, "max_size", text="")
        row.prop(history, "current_id", text="")

        # === BOOKMARK LIBRARIES === #
        settings.libraries.draw(context, layout)

        library = settings.libraries.get_item()

        if library is None:
            return

        row = layout.row()
        row.prop(settings, "show_bookmarks",
            text="", icon='RESTRICT_VIEW_OFF')
        row = row.row(align=True)
        row.prop(library, "system", text="")
        row.prop(library, "offset", text="",
            icon='ARROW_LEFTRIGHT')

        # === BOOKMARKS === #
        library.bookmarks.draw(context, layout)

        if len(library.bookmarks.collection) == 0:
            return

        row = layout.row()
        row = row.split(align=True)
        # PASTEDOWN
        # COPYDOWN
        row.operator("scene.cursor_3d_overwrite_bookmark",
            text="", icon='REC')
        row.operator("scene.cursor_3d_swap_bookmark",
            text="", icon='FILE_REFRESH')
        row.operator("scene.cursor_3d_recall_bookmark",
            text="", icon='FILE_TICK')
        row.operator("scene.cursor_3d_add_empty_at_bookmark",
            text="", icon='EMPTY_DATA')
        # Not implemented (and maybe shouldn't)
        #row.operator("scene.cursor_3d_snap_selection_to_bookmark",
        #    text="", icon='SNAP_ON')

@addon.Operator(idname="view3d.set_cursor3d_dialog", label="Set 3D Cursor", description="Set 3D Cursor XYZ values")
class SetCursorDialog:
    pos = Vector() | prop("3D Cursor location in current coordinate system", "Location")

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'

    def execute(self, context):
        scene = context.scene

        # "current system" / "relative" could have changed
        self.matrix = self.csu.get_matrix()

        pos = self.matrix * self.pos
        set_cursor_location(pos, v3d=context.space_data)

        return {'FINISHED'}

    def invoke(self, context, event):
        scene = context.scene

        cursor_pos = get_cursor_location(v3d=context.space_data)

        particles, self.csu = gather_particles(context=context)
        self.csu.source_pos = cursor_pos

        self.matrix = self.csu.get_matrix()

        try:
            self.pos = self.matrix.inverted() * cursor_pos
        except:
            # this is some degenerate system
            self.pos = Vector()

        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=160)

    def draw(self, context):
        layout = self.layout

        settings = find_settings()
        tfm_opts = settings.transform_options

        v3d = context.space_data

        col = layout.column()
        col.prop(self, "pos", text="")

        row = layout.row()
        row.prop(tfm_opts, "use_relative_coords", text="Relative")
        row.prop(v3d, "transform_orientation", text="")

@addon.PropertyGroup
class AlignOrientationProperties:
    axes_items = [
        ('X', 'X', 'X axis'),
        ('Y', 'Y', 'Y axis'),
        ('Z', 'Z', 'Z axis'),
        ('-X', '-X', '-X axis'),
        ('-Y', '-Y', '-Y axis'),
        ('-Z', '-Z', '-Z axis'),
    ]

    axes_items_ = [
        ('X', 'X', 'X axis'),
        ('Y', 'Y', 'Y axis'),
        ('Z', 'Z', 'Z axis'),
        (' ', ' ', 'Same as source axis'),
    ]

    def get_orients(self, context):
        orients = []
        orients.append(('GLOBAL', "Global", ""))
        orients.append(('LOCAL', "Local", ""))
        orients.append(('GIMBAL', "Gimbal", ""))
        orients.append(('NORMAL', "Normal", ""))
        orients.append(('VIEW', "View", ""))

        for orientation in context.scene.orientations:
            name = orientation.name
            orients.append((name, name, ""))

        return orients
    
    src_axis = 'Z' | prop(name="Initial axis", items=axes_items)
    #src_orient = 'GLOBAL' | prop(items=get_orients)
    dest_axis = ' ' | prop(name="Final axis", items=axes_items_)
    dest_orient = 'GLOBAL' | prop(name="Final orientation", items=get_orients)

@addon.Operator(idname="view3d.align_orientation", label="Align Orientation", description="Rotates active object to match axis of current orientation to axis of another orientation", options={'REGISTER', 'UNDO'})
class AlignOrientation:
    axes_items = [
        ('X', 'X', 'X axis'),
        ('Y', 'Y', 'Y axis'),
        ('Z', 'Z', 'Z axis'),
        ('-X', '-X', '-X axis'),
        ('-Y', '-Y', '-Y axis'),
        ('-Z', '-Z', '-Z axis'),
    ]

    axes_items_ = [
        ('X', 'X', 'X axis'),
        ('Y', 'Y', 'Y axis'),
        ('Z', 'Z', 'Z axis'),
        (' ', ' ', 'Same as source axis'),
    ]

    axes_ids = {'X':0, 'Y':1, 'Z':2}

    def get_orients(self, context):
        orients = []
        orients.append(('GLOBAL', "Global", ""))
        orients.append(('LOCAL', "Local", ""))
        orients.append(('GIMBAL', "Gimbal", ""))
        orients.append(('NORMAL', "Normal", ""))
        orients.append(('VIEW', "View", ""))

        for orientation in context.scene.orientations:
            name = orientation.name
            orients.append((name, name, ""))

        return orients

    src_axis = 'Z' | prop(name="Initial axis", items=axes_items)
    #src_orient = 'GLOBAL' | prop(items=get_orients)
    dest_axis = ' ' | prop(name="Final axis", items=axes_items_)
    dest_orient = 'GLOBAL' | prop(name="Final orientation", items=get_orients)

    @classmethod
    def poll(cls, context):
        return (context.area.type == 'VIEW_3D') and context.object

    def execute(self, context):
        wm = context.window_manager
        obj = context.object
        scene = context.scene
        v3d = context.space_data
        rv3d = context.region_data

        particles, csu = gather_particles(context=context)
        tou = csu.tou
        #tou = TransformOrientationUtility(scene, v3d, rv3d)

        aop = wm.align_orientation_properties # self

        src_matrix = tou.get_matrix()
        src_axes = matrix_decompose(src_matrix)
        src_axis_name = aop.src_axis
        if src_axis_name.startswith("-"):
            src_axis_name = src_axis_name[1:]
            src_axis = -src_axes[self.axes_ids[src_axis_name]]
        else:
            src_axis = src_axes[self.axes_ids[src_axis_name]]

        tou.set(aop.dest_orient, False)
        dest_matrix = tou.get_matrix()
        dest_axes = matrix_decompose(dest_matrix)
        if self.dest_axis != ' ':
            dest_axis_name = aop.dest_axis
        else:
            dest_axis_name = src_axis_name
        dest_axis = dest_axes[self.axes_ids[dest_axis_name]]

        q = src_axis.rotation_difference(dest_axis)

        m = obj.matrix_world.to_3x3()
        m.rotate(q)
        m.resize_4x4()
        m.translation = obj.matrix_world.translation.copy()

        obj.matrix_world = m

        #bpy.ops.ed.undo_push(message="Align Orientation")

        return {'FINISHED'}

    # ATTENTION!
    # This _must_ be a dialog, because with 'UNDO' option
    # the last selected orientation may revert to the previous state
    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self, width=200)

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        aop = wm.align_orientation_properties # self
        layout.prop(aop, "src_axis")
        layout.prop(aop, "dest_axis")
        layout.prop(aop, "dest_orient")

@addon.Operator(idname="view3d.copy_orientation", label="Copy Orientation", description="Makes a copy of current orientation")
class CopyOrientation:
    def execute(self, context):
        scene = context.scene
        v3d = context.space_data
        rv3d = context.region_data

        particles, csu = gather_particles(context=context)
        tou = csu.tou
        #tou = TransformOrientationUtility(scene, v3d, rv3d)

        orient = create_transform_orientation(scene,
            name=tou.get()+".copy", matrix=tou.get_matrix())

        tou.set(orient.name)

        return {'FINISHED'}

def transform_orientations_panel_extension(self, context):
    row = self.layout.row()
    row.operator("view3d.align_orientation", text="Align")
    row.operator("view3d.copy_orientation", text="Copy")

# ===== CURSOR MONITOR ===== #
@addon.Operator(idname="view3d.cursor3d_monitor", label="Cursor Monitor", description="Monitor changes in cursor location and write to history")
class CursorMonitor:
    # A class-level variable (it must be accessed from poll())
    is_running = False

    storage = {}

    _handle_view = None
    _handle_px = None
    _handle_header_px = None

    script_reload_kmis = []

    @staticmethod
    def handle_add(self, context):
        CursorMonitor._handle_view = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_view, (self, context), 'WINDOW', 'POST_VIEW')
        CursorMonitor._handle_px = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_px, (self, context), 'WINDOW', 'POST_PIXEL')
        CursorMonitor._handle_header_px = bpy.types.SpaceView3D.draw_handler_add(
            draw_callback_header_px, (self, context), 'HEADER', 'POST_PIXEL')

    @staticmethod
    def handle_remove(context):
        if CursorMonitor._handle_view is not None:
            bpy.types.SpaceView3D.draw_handler_remove(CursorMonitor._handle_view, 'WINDOW')
        if CursorMonitor._handle_px is not None:
            bpy.types.SpaceView3D.draw_handler_remove(CursorMonitor._handle_px, 'WINDOW')
        if CursorMonitor._handle_header_px is not None:
            bpy.types.SpaceView3D.draw_handler_remove(CursorMonitor._handle_header_px, 'HEADER')
        CursorMonitor._handle_view = None
        CursorMonitor._handle_px = None
        CursorMonitor._handle_header_px = None

    @classmethod
    def poll(cls, context):
        try:
            runtime_settings = find_runtime_settings()
            if not runtime_settings:
                return False

            # When addon is enabled by default and
            # user started another new scene, is_running
            # would still be True
            return (not CursorMonitor.is_running) or \
                (runtime_settings.current_monitor_id == 0)
        except Exception as e:
            print("Cursor monitor exeption in poll:\n" + repr(e))
            return False

    def modal(self, context, event):
        # Scripts cannot be reloaded while modal operators are running
        # Intercept the corresponding event and shut down CursorMonitor
        # (it would be relaunched automatically afterwards)
        for kmi in CursorMonitor.script_reload_kmis:
            if IsKeyMapItemEvent(kmi, event):
                return {'CANCELLED'}
        
        try:
            return self._modal(context, event)
        except Exception as e:
            print("Cursor monitor exeption in modal:\n" + repr(e))
            # Remove callbacks at any cost
            self.cancel(context)
            #raise
            return {'CANCELLED'}

    def _modal(self, context, event):
        runtime_settings = find_runtime_settings()

        # ATTENTION: will this work correctly when another
        # blend is loaded? (it should, since all scripts
        # seem to be reloaded in such case)
        if (runtime_settings is None) or \
                (self.id != runtime_settings.current_monitor_id):
            # Another (newer) monitor was launched;
            # this one should stop.
            # (OR addon was disabled)
            self.cancel(context)
            return {'CANCELLED'}

        # Somewhy after addon re-registration
        # this permanently becomes False
        CursorMonitor.is_running = True

        if self.update_storage(runtime_settings):
            # hmm... can this cause flickering of menus?
            context.area.tag_redraw()

        settings = find_settings()
        
        propagate_settings_to_all_screens(settings)

        # ================== #
        # Update bookmark enums when addon is initialized.
        # Since CursorMonitor operator can be called from draw(),
        # we have to postpone all re-registration-related tasks
        # (such as redefining the enums).
        if self.just_initialized:
            # update the relevant enums, bounds and other options
            # (is_running becomes False once another scene is loaded,
            # so this operator gets restarted)
            settings.history.update_max_size()
            settings.libraries.update_enum()
            library = settings.libraries.get_item()
            if library:
                library.bookmarks.update_enum()

            self.just_initialized = False
        # ================== #

        # Seems like recalc_csu() in this place causes trouble
        # if space type is switched from 3D to e.g. UV
        '''
        tfm_operator = CursorDynamicSettings.active_transform_operator
        if tfm_operator:
            CursorDynamicSettings.csu = tfm_operator.csu
        else:
            CursorDynamicSettings.recalc_csu(context, event.value)
        '''

        return {'PASS_THROUGH'}

    def update_storage(self, runtime_settings):
        if CursorDynamicSettings.active_transform_operator:
            # Don't add to history while operator is running
            return False

        new_pos = None

        last_locations = {}

        for scene in bpy.data.scenes:
            # History doesn't depend on view (?)
            curr_pos = get_cursor_location(scene=scene)

            last_locations[scene.name] = curr_pos

            # Ignore newly-created or some renamed scenes
            if scene.name in self.last_locations:
                if curr_pos != self.last_locations[scene.name]:
                    new_pos = curr_pos
            elif runtime_settings.current_monitor_id == 0:
                # startup location should be added
                new_pos = curr_pos

        # Seems like scene.cursor_location is fast enough here
        # -> no need to resort to v3d.cursor_location.
        """
        screen = bpy.context.screen
        scene = screen.scene
        v3d = None
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    v3d = space
                    break

        if v3d is not None:
            curr_pos = get_cursor_location(v3d=v3d)

            last_locations[scene.name] = curr_pos

            # Ignore newly-created or some renamed scenes
            if scene.name in self.last_locations:
                if curr_pos != self.last_locations[scene.name]:
                    new_pos = curr_pos
        """

        self.last_locations = last_locations

        if new_pos is not None:
            settings = find_settings()
            history = settings.history

            pos = history.get_pos()
            if (pos is not None):# and (history.current_id != 0): # ?
                if pos == new_pos:
                    return False # self.just_initialized ?

            entry = history.entries.add()
            entry.pos = new_pos

            last_id = len(history.entries) - 1
            history.entries.move(last_id, 0)

            if last_id > int(history.max_size):
                history.entries.remove(last_id)

            # make sure the most recent history entry is displayed

            CursorHistoryProp.update_cursor_on_id_change = False
            history.current_id = 0
            CursorHistoryProp.update_cursor_on_id_change = True

            history.curr_id = history.current_id
            history.last_id = 1

            return True

        return False # self.just_initialized ?

    def execute(self, context):
        print("Cursor monitor: launched")

        CursorMonitor.script_reload_kmis = list(KeyMapItemSearch('script.reload'))

        runtime_settings = find_runtime_settings()

        self.just_initialized = True

        self.id = 0

        self.last_locations = {}

        # Important! Call update_storage() before assigning
        # current_monitor_id (used to add startup cursor location)
        self.update_storage(runtime_settings)

        # Indicate that this is the most recent monitor.
        # All others should shut down.
        self.id = runtime_settings.current_monitor_id + 1
        runtime_settings.current_monitor_id = self.id

        CursorMonitor.is_running = True

        CursorDynamicSettings.recalc_csu(context, 'PRESS')

        # I suppose that cursor position would change
        # only with user interaction.
        #self._timer = context.window_manager. \
        #    event_timer_add(0.1, context.window)

        CursorMonitor.handle_add(self, context)

        # Here we cannot return 'PASS_THROUGH',
        # or Blender will crash!

        # Currently there seems to be only one window
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        CursorMonitor.is_running = False
        #type(self).is_running = False

        # Unregister callbacks...
        CursorMonitor.handle_remove(context)



# ===== DRAWING CALLBACKS ===== #
cursor_save_location = Vector()

def draw_callback_view(self, context):
    global cursor_save_location

    settings = find_settings()
    if settings is None:
        return

    update_stick_to_obj(context)

    if "EDIT" not in context.mode:
        # It's nice to have bookmark position update interactively
        # However, this still can be slow if there are many
        # selected objects

        # ATTENTION!!!
        # This eats a lot of processor time!
        #CursorDynamicSettings.recalc_csu(context, 'PRESS')
        pass

    history = settings.history

    tfm_operator = CursorDynamicSettings.active_transform_operator

    is_drawing = history.show_trace or tfm_operator

    if is_drawing:
        # Store previous OpenGL settings
        MatrixMode_prev = gl_get(bgl.GL_MATRIX_MODE)
        ProjMatrix_prev = gl_get(bgl.GL_PROJECTION_MATRIX)
        lineWidth_prev = gl_get(bgl.GL_LINE_WIDTH)
        blend_prev = gl_get(bgl.GL_BLEND)
        line_stipple_prev = gl_get(bgl.GL_LINE_STIPPLE)
        color_prev = gl_get(bgl.GL_COLOR)
        smooth_prev = gl_get(bgl.GL_SMOOTH)
        depth_test_prev = gl_get(bgl.GL_DEPTH_TEST)
        depth_mask_prev = gl_get(bgl.GL_DEPTH_WRITEMASK)

    if history.show_trace:
        bgl.glDepthRange(0.0, 0.9999)

        history.draw_trace(context)

        library = settings.libraries.get_item()
        if library and library.offset:
            history.draw_offset(context)

        bgl.glDepthRange(0.0, 1.0)

    if tfm_operator:
        tfm_operator.draw_3d(context)

    if is_drawing:
        # Restore previous OpenGL settings
        bgl.glLineWidth(lineWidth_prev)
        gl_enable(bgl.GL_BLEND, blend_prev)
        gl_enable(bgl.GL_LINE_STIPPLE, line_stipple_prev)
        gl_enable(bgl.GL_SMOOTH, smooth_prev)
        gl_enable(bgl.GL_DEPTH_TEST, depth_test_prev)
        bgl.glDepthMask(depth_mask_prev)
        bgl.glColor4f(color_prev[0],
            color_prev[1],
            color_prev[2],
            color_prev[3])

    cursor_save_location = Vector(context.space_data.cursor_location)
    if not settings.cursor_visible:
        # This is causing problems! See <https://developer.blender.org/T33197>
        #bpy.context.space_data.cursor_location = Vector([float('nan')] * 3)

        region = context.region
        v3d = context.space_data
        rv3d = context.region_data

        pixelsize = 1
        dpi = context.user_preferences.system.dpi
        widget_unit = (pixelsize * dpi * 20.0 + 36.0) / 72.0

        cursor_w = widget_unit*2
        cursor_h = widget_unit*2

        viewinv = rv3d.view_matrix.inverted()
        persinv = rv3d.perspective_matrix.inverted()

        origin_start = viewinv.translation
        view_direction = viewinv.col[2].xyz#.normalized()
        depth_location = origin_start - view_direction

        coord = (-cursor_w, -cursor_h)
        dx = (2.0 * coord[0] / region.width) - 1.0
        dy = (2.0 * coord[1] / region.height) - 1.0
        p = ((persinv.col[0].xyz * dx) +
             (persinv.col[1].xyz * dy) +
             depth_location)

        context.space_data.cursor_location = p

def draw_callback_header_px(self, context):
    r = context.region

    tfm_operator = CursorDynamicSettings.active_transform_operator
    if not tfm_operator:
        return

    smooth_prev = gl_get(bgl.GL_SMOOTH)

    tfm_operator.draw_axes_coords(context, (r.width, r.height))

    gl_enable(bgl.GL_SMOOTH, smooth_prev)

    bgl.glDisable(bgl.GL_BLEND)
    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)

def draw_callback_px(self, context):
    global cursor_save_location
    settings = find_settings()
    if settings is None:
        return
    library = settings.libraries.get_item()

    if not settings.cursor_visible:
        context.space_data.cursor_location = cursor_save_location

    tfm_operator = CursorDynamicSettings.active_transform_operator

    if settings.show_bookmarks and library:
        library.draw_bookmark(context)

    if tfm_operator:
        tfm_operator.draw_2d(context)

    # restore opengl defaults
    bgl.glLineWidth(1)
    bgl.glDisable(bgl.GL_BLEND)
    bgl.glColor4f(0.0, 0.0, 0.0, 1.0)



# ===== REGISTRATION ===== #
def update_keymap(activate):
    reg_idname = DelayRegistrationOperator.bl_idname
    enh_idname = EnhancedSetCursor.bl_idname
    cur_idname = 'view3d.cursor3d'

    wm = bpy.context.window_manager
    userprefs = bpy.context.user_preferences
    addon_prefs = userprefs.addons[__name__].preferences
    settings = find_settings()

    if not (settings.auto_register_keymaps and addon_prefs.auto_register_keymaps):
        return

    try:
        km = wm.keyconfigs.user.keymaps['3D View']
    except:
        # wm.keyconfigs.user is empty on Blender startup!
        if activate:
            # activate temporary operator
            km = wm.keyconfigs.active.keymaps['Window']
            kmi = km.keymap_items.new(reg_idname, 'MOUSEMOVE', 'ANY')
        return

    # We need for the enhanced operator to take precedence over
    # the default cursor3d, but not over the manipulator.
    # If we add the operator to "addon" keymaps, it will
    # take precedence over both. If we add it to "user"
    # keymaps, the default will take precedence.
    # However, we may just simply turn it off or remove
    # (depending on what saves with blend).

    items = list(KeyMapItemSearch(enh_idname, km))
    if activate and (len(items) == 0):
        kmi = km.keymap_items.new(enh_idname, 'ACTIONMOUSE', 'PRESS')
        for key in EnhancedSetCursor.key_map["free_mouse"]:
            kmi = km.keymap_items.new(enh_idname, key, 'PRESS')
    else:
        for kmi in items:
            if activate:
                kmi.active = activate
            else:
                km.keymap_items.remove(kmi)

    for kmi in KeyMapItemSearch(cur_idname):
        kmi.active = not activate

@addon.Operator(idname="wm.enhanced_3d_cursor_registration", label="[Enhanced 3D Cursor] registration delayer")
class DelayRegistrationOperator:
    _timer = None

    @staticmethod
    def timer_add(context):
        DelayRegistrationOperator._timer = \
            context.window_manager.event_timer_add(0.1, context.window)

    @staticmethod
    def timer_remove(context):
        if DelayRegistrationOperator._timer is not None:
            context.window_manager.event_timer_remove(DelayRegistrationOperator._timer)
            DelayRegistrationOperator._timer = None

    def modal(self, context, event):
        if (not self.keymap_updated) and \
            ((event.type == 'TIMER') or ("MOVE" in event.type)):
            # clean up (we don't need this operator to run anymore)
            for kmi in KeyMapItemSearch(self.bl_idname):
                km.keymap_items.remove(kmi)

            update_keymap(True)

            self.keymap_updated = True

            # No, better don't (at least in current version),
            # since the monitor has dependencies on View3D context.
            # Attempt to launch the monitor
            #if bpy.ops.view3d.cursor3d_monitor.poll():
            #    bpy.ops.view3d.cursor3d_monitor()

            self.cancel(context)
            return {'CANCELLED'}

        return {'PASS_THROUGH'}

    def execute(self, context):
        self.keymap_updated = False

        DelayRegistrationOperator.timer_add(context)

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        DelayRegistrationOperator.timer_remove(context)

@addon.Preferences.Include
class ThisAddonPreferences:
    auto_register_keymaps = True | prop(name="Auto Register Keymaps")
    
    def draw(self, context):
        layout = self.layout
        settings = find_settings()
        row = layout.row()
        row.prop(self, "auto_register_keymaps", text="")
        row.prop(settings, "auto_register_keymaps")
        row.prop(settings, "free_coord_precision")


def register():
    addon.register()

    bpy.types.Scene.cursor_3d_tools_settings = bpy.props.PointerProperty(type=Cursor3DToolsSceneSettings)

    bpy.types.Screen.cursor_3d_tools_settings = bpy.props.PointerProperty(type=Cursor3DToolsSettings)

    bpy.types.WindowManager.align_orientation_properties = bpy.props.PointerProperty(type=AlignOrientationProperties)

    bpy.types.WindowManager.cursor_3d_runtime_settings = bpy.props.PointerProperty(type=CursorRuntimeSettings)

    bpy.types.VIEW3D_PT_transform_orientations.append(transform_orientations_panel_extension)

    # View properties panel is already long. Appending something
    # to it would make it too inconvenient
    #bpy.types.VIEW3D_PT_view3d_properties.append(draw_cursor_tools)
    
    # THIS IS WHAT CAUSES TOOLTIPS TO NOT SHOW!
    update_keymap(True)


def unregister():
    # In case they are enabled/active
    CursorMonitor.handle_remove(bpy.context)
    DelayRegistrationOperator.timer_remove(bpy.context)

    # Manually set this to False on unregister
    CursorMonitor.is_running = False

    update_keymap(False)

    addon.unregister()

    if hasattr(bpy.types.Scene, "cursor_3d_tools_settings"):
        del bpy.types.Scene.cursor_3d_tools_settings

    if hasattr(bpy.types.Screen, "cursor_3d_tools_settings"):
        del bpy.types.Screen.cursor_3d_tools_settings

    if hasattr(bpy.types.WindowManager, "align_orientation_properties"):
        del bpy.types.WindowManager.align_orientation_properties

    if hasattr(bpy.types.WindowManager, "cursor_3d_runtime_settings"):
        del bpy.types.WindowManager.cursor_3d_runtime_settings

    bpy.types.VIEW3D_PT_transform_orientations.remove(
        transform_orientations_panel_extension)

    #bpy.types.VIEW3D_PT_view3d_properties.remove(draw_cursor_tools)




'''
@addon.Preferences.Include
class ThisAddonPreferences:
    pass

def register():
    # I couldn't find a way to avoid the unpredictable crashes,
    # and some actions (like changing a material in material slot)
    # cannot be detected through the info log anyway.
    #addon.handler_append("scene_update_post", scene_update_post)
    
    addon.register()
    
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Window")
        kmi = km.keymap_items.new("object.batch_properties_copy", 'C', 'PRESS', ctrl=True)
        kmi = km.keymap_items.new("object.batch_properties_paste", 'V', 'PRESS', ctrl=True)

def unregister():
    # Note: if we remove from non-addon keyconfigs, the keymap registration
    # won't work on the consequent addon enable/reload (until Blender restarts)
    kc = bpy.context.window_manager.keyconfigs.addon
    KeyMapUtils.remove("object.batch_properties_copy", place=kc)
    KeyMapUtils.remove("object.batch_properties_paste", place=kc)
    
    addon.unregister()
    
    # don't remove this, or on next addon enable the monitor will consider itself already running
    #ChangeMonitoringOperator.is_running = False
'''
