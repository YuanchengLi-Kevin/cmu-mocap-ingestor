# Copyright (c) 2026 Yuancheng Li
# SPDX-License-Identifier: Apache-2.0

import subprocess
from pathlib import Path

import bpy

repo_root = Path(__file__).resolve().parents[1]
bvh_path = repo_root / "data/source/cmu-mocap/data/001/01_01.bvh"
export_path = repo_root / "data/assets/previews/cmu_01_01_test.glb"
gltfpack_enabled = True
gltfpack_path = "gltfpack"
gltfpack_args = ["-kn", "-cc"]
source_frame_rate = 120.0
export_frame_rate = 30.0

target_rig_name = "Armature"
source_rig_name = "01_01"


def operator_kwargs(operator, values):
    supported = {prop.identifier for prop in operator.get_rna_type().properties}
    return {key: value for key, value in values.items() if key in supported}


def export_animation_glb(path, armature):
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    kwargs = operator_kwargs(
        bpy.ops.export_scene.gltf,
        {
            "filepath": str(path),
            "export_format": "GLB",
            "use_selection": True,
            "export_animations": True,
            "export_frame_range": True,
            "export_force_sampling": True,
            "export_optimize_animation_size": True,
            "export_skins": True,
            "export_def_bones": True,
            "export_materials": "NONE",
            "export_cameras": False,
            "export_lights": False,
            "export_morph": False,
            "export_extras": False,
        },
    )
    result = bpy.ops.export_scene.gltf(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"GLB export failed: {sorted(result)}")


def raw_glb_path(path):
    path = Path(path)
    return path.with_name(f"{path.stem}.raw{path.suffix}")


def retime_action(action, source_fps, target_fps, frame_start):
    if target_fps <= 0:
        raise ValueError("target_fps must be positive")

    fcurves = action_fcurves(action)
    if not fcurves:
        raise RuntimeError("Target action has no editable F-curves")

    ratio = target_fps / source_fps
    for fcurve in fcurves:
        for keyframe in fcurve.keyframe_points:
            for point in (keyframe.co, keyframe.handle_left, keyframe.handle_right):
                point.x = frame_start + ((point.x - frame_start) * ratio)
        fcurve.update()


def action_fcurves(action):
    fcurves = []
    seen = set()
    stack = [action]

    while stack:
        value = stack.pop()
        pointer = value_pointer(value)
        if pointer in seen:
            continue
        seen.add(pointer)

        maybe_fcurves = optional_attr(value, "fcurves")
        if maybe_fcurves is not None:
            for fcurve in iterable_values(maybe_fcurves):
                if optional_attr(fcurve, "keyframe_points") is not None:
                    fcurves.append(fcurve)

        for attribute in ("layers", "strips", "channelbags", "channels", "groups", "slots"):
            child_values = optional_attr(value, attribute)
            if child_values is not None:
                stack.extend(iterable_values(child_values))

    return fcurves


def optional_attr(value, name):
    try:
        return getattr(value, name)
    except (AttributeError, TypeError, RuntimeError):
        return None


def iterable_values(value):
    try:
        return list(value)
    except TypeError:
        return []


def value_pointer(value):
    as_pointer = optional_attr(value, "as_pointer")
    if callable(as_pointer):
        try:
            return int(as_pointer())
        except RuntimeError:
            pass
    return id(value)


def run_gltfpack(executable, input_path, output_path, extra_args):
    command = [
        executable,
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        *extra_args,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"gltfpack executable not found: {executable}") from error

    if result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        raise RuntimeError(f"gltfpack failed with exit code {result.returncode}\n{output}")


bpy.ops.import_anim.bvh(filepath=str(bvh_path))

source = bpy.data.objects[source_rig_name]
target = bpy.data.objects[target_rig_name]
source_action = source.animation_data.action
bpy.context.scene.frame_start = int(source_action.frame_range[0])
bpy.context.scene.frame_end = int(source_action.frame_range[1])
bpy.context.scene.render.fps = int(round(source_frame_rate))

bpy.context.scene.rsl_retargeting_armature_source = source
bpy.context.scene.rsl_retargeting_armature_target = target

# Use the currently posed rigs as Rokoko's reference pose.
bpy.context.scene.rsl_retargeting_use_pose = 'CURRENT'

bpy.ops.rsl.build_bone_list()

ignored_hand_bones = {
    "LeftFingerBase",
    "LeftHandIndex1",
    "LThumb",
    "RightFingerBase",
    "RightHandIndex1",
    "RThumb",
    "mixamorig:LeftFingerBase",
    "mixamorig:LeftHandIndex1",
    "mixamorig:LThumb",
    "mixamorig:RightFingerBase",
    "mixamorig:RightHandIndex1",
    "mixamorig:RThumb",
}

def has_ignored_hand_bone(item):
    for prop in item.bl_rna.properties:
        if prop.identifier == "rna_type":
            continue
        try:
            value = getattr(item, prop.identifier)
        except AttributeError:
            continue
        if isinstance(value, str) and value in ignored_hand_bones:
            return True
    return False


bone_list = bpy.context.scene.rsl_retargeting_bone_list
for index in range(len(bone_list) - 1, -1, -1):
    if has_ignored_hand_bone(bone_list[index]):
        bone_list.remove(index)

bpy.ops.rsl.retarget_animation()

if target.animation_data is None or target.animation_data.action is None:
    raise RuntimeError("Target armature has no retargeted action")
target_action = target.animation_data.action
ratio = export_frame_rate / source_frame_rate
frame_start = bpy.context.scene.frame_start
bpy.context.scene.frame_end = max(
    frame_start,
    int(round(frame_start + ((bpy.context.scene.frame_end - frame_start) * ratio))),
)
bpy.context.scene.render.fps = int(round(export_frame_rate))
retime_action(
    target_action,
    source_fps=source_frame_rate,
    target_fps=export_frame_rate,
    frame_start=frame_start,
)

bpy.data.objects.remove(source, do_unlink=True)
for action in list(bpy.data.actions):
    if action != target_action:
        bpy.data.actions.remove(action)

if gltfpack_enabled:
    raw_export_path = raw_glb_path(export_path)
    export_animation_glb(str(raw_export_path), target)
    run_gltfpack(
        executable=gltfpack_path,
        input_path=raw_export_path,
        output_path=export_path,
        extra_args=gltfpack_args,
    )
    raw_export_path.unlink(missing_ok=True)
else:
    export_animation_glb(export_path, target)

print(f"SUCCESS: Exported {export_path}")
