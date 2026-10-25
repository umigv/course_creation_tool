#!/usr/bin/env python3
"""
3D perspective view of the obstacle heightmap, with an orbit camera and ray picking.

Each obstacle cell is a solid column from the ground (z = 0) up to its height. World axes match the 2D view:
+x right / east, +y up / north, and +z is height.

Rendering uses the painter's algorithm: the ground (grid, lane lines) is drawn first, then obstacle faces from far to
near. The rendered scene is cached and only redrawn when the camera, the viewport or the map changes.
"""

import math
from dataclasses import dataclass

import numpy as np
import pygame

from map_renderer_base import (
    BACKGROUND_COLOR, GRID_MINOR, GRID_MAJOR, GRID_SUPER, AXIS_COLOR, LANE_LINE_COLOR,
    CELL_RESOLUTION, MAJOR_EVERY, SUPER_EVERY, height_color,
)


# ── Constants ──────────────────────────────────────────────────────────────────
NEAR_PLANE_M      = 0.05
FOV_RAD           = math.radians(50)
MIN_DISTANCE_M    = 0.5
MAX_DISTANCE_M    = 5000.0
MIN_PITCH_RAD     = math.radians(5)
MAX_PITCH_RAD     = math.radians(89)
ORBIT_RAD_PER_PX  = 0.008
DEFAULT_YAW_RAD   = -math.pi / 2       # Camera south of the target, looking north (+y)
DEFAULT_PITCH_RAD = math.radians(50)
DEFAULT_DISTANCE_M = 20.0
MAX_TOP_RUN       = 8                  # Max blocks merged into one top face, keeps depth sorting stable
MAX_PICK_STEPS    = 200_000

# Shade per face direction, applied to the (lightened) height color
TOP_SHADE   = 1.0
SIDE_SHADES = {(1, 0): 0.72, (-1, 0): 0.52, (0, 1): 0.60, (0, -1): 0.84}
LIGHTEN_3D  = 0.4   # Mix obstacle colors toward white so face shading stays visible on dark colors
EDGE_SHADE  = 0.6


def _shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def _lighten(color, amount):
    return tuple(int(c + (255 - c) * amount) for c in color)


@dataclass(frozen=True)
class Pick:
    """Result of casting a screen ray into the map."""
    cell: tuple[int, int]                 # Base cell hit (obstacle column, or ground cell)
    point: tuple[float, float, float]     # World hit point (m)
    surface_z: float                      # Top of the hit column, or 0 for ground


# ─────────────────────────────────────────────────────────────────────────────
# Camera
# ─────────────────────────────────────────────────────────────────────────────
class OrbitCamera:
    """Perspective camera orbiting a target point on the ground."""

    def __init__(self):
        self.width = 1
        self.height = 1
        self.reset()

    def reset(self):
        self.target_x = 0.0
        self.target_y = 0.0
        self.yaw = DEFAULT_YAW_RAD        # Direction from target to eye, around +z
        self.pitch = DEFAULT_PITCH_RAD    # Elevation of the eye above the ground plane
        self.distance = DEFAULT_DISTANCE_M

    def state(self):
        return (self.target_x, self.target_y, self.yaw, self.pitch, self.distance, self.width, self.height)

    @property
    def focal_px(self):
        return (self.height / 2) / math.tan(FOV_RAD / 2)

    def basis(self):
        """Return (eye, right, up, forward) as numpy vectors."""
        cos_pitch, sin_pitch = math.cos(self.pitch), math.sin(self.pitch)
        cos_yaw, sin_yaw = math.cos(self.yaw), math.sin(self.yaw)
        eye = np.array([self.target_x + self.distance * cos_pitch * cos_yaw,
                        self.target_y + self.distance * cos_pitch * sin_yaw,
                        self.distance * sin_pitch])
        forward = np.array([-cos_pitch * cos_yaw, -cos_pitch * sin_yaw, -sin_pitch])
        right = np.array([-sin_yaw, cos_yaw, 0.0])
        up = np.cross(right, forward)
        return eye, right, up, forward

    def project(self, x, y, z):
        """World point -> screen (x, y), or None if behind the near plane."""
        eye, right, up, forward = self.basis()
        offset = np.array([x, y, z]) - eye
        depth = float(offset @ forward)
        if depth < NEAR_PLANE_M:
            return None
        focal = self.focal_px
        return (self.width / 2 + focal * float(offset @ right) / depth,
                self.height / 2 - focal * float(offset @ up) / depth)

    def ray(self, screen_x, screen_y):
        """Return (origin, unit direction) of the ray through a screen pixel."""
        eye, right, up, forward = self.basis()
        focal = self.focal_px
        direction = forward + ((screen_x - self.width / 2) / focal) * right - ((screen_y - self.height / 2) / focal) * up
        return eye, direction / np.linalg.norm(direction)

    def ground_point(self, screen_x, screen_y):
        """Where the ray through a pixel meets z = 0, as (x, y), or None if it points at the sky."""
        origin, direction = self.ray(screen_x, screen_y)
        if direction[2] >= -1e-9:
            return None
        t = -origin[2] / direction[2]
        return float(origin[0] + direction[0] * t), float(origin[1] + direction[1] * t)

    def world_per_pixel(self, x, y, z=0.0):
        """Approximate world size (m) of one pixel at a world point."""
        eye, _, _, _ = self.basis()
        return float(np.linalg.norm(np.array([x, y, z]) - eye)) / self.focal_px

    def orbit(self, dx_px, dy_px):
        self.yaw -= dx_px * ORBIT_RAD_PER_PX
        self.pitch = max(MIN_PITCH_RAD, min(MAX_PITCH_RAD, self.pitch + dy_px * ORBIT_RAD_PER_PX))

    def pan_to_keep(self, grab_point, screen_x, screen_y):
        """Move the target so the ground point `grab_point` sits under (screen_x, screen_y)."""
        current = self.ground_point(screen_x, screen_y)
        if grab_point is None or current is None:
            return
        self.target_x += grab_point[0] - current[0]
        self.target_y += grab_point[1] - current[1]

    def zoom_at(self, delta, screen_x, screen_y):
        """Dolly toward (delta > 0) or away from the ground point under the cursor."""
        factor = 1 / 1.15 if delta > 0 else 1.15
        new_distance = max(MIN_DISTANCE_M, min(MAX_DISTANCE_M, self.distance * factor))
        factor = new_distance / self.distance
        anchor = self.ground_point(screen_x, screen_y)
        # Zooming toward a point near the horizon would throw the target far away; zoom about the target instead.
        if anchor is not None and math.hypot(anchor[0] - self.target_x, anchor[1] - self.target_y) < 20 * self.distance:
            self.target_x = anchor[0] + (self.target_x - anchor[0]) * factor
            self.target_y = anchor[1] + (self.target_y - anchor[1]) * factor
        self.distance = new_distance


# ─────────────────────────────────────────────────────────────────────────────
# Renderer
# ─────────────────────────────────────────────────────────────────────────────
class MapRenderer3D:
    """Renders obstacles and lane lines in 3D into the canvas area (left `canvas_width` pixels of the screen)."""

    def __init__(self, screen, canvas_width, dimensions):
        self.screen = screen
        self.canvas_width = canvas_width
        self.dimensions = dimensions   # Shared ScaledDimensions from the 2D renderer
        self.camera = OrbitCamera()

        self._scene: pygame.Surface | None = None
        self._scene_key = None
        self._map_dirty = True
        self._mesh_block = None
        self._obstacle_mesh = None
        self._lane_mesh = None

    # ── Map / camera state ──────────────────────────────────────────────────────
    def invalidate_map(self):
        """Call whenever obstacles or lane lines change."""
        self._map_dirty = True

    def _sync_viewport(self):
        self.camera.width = max(1, self.canvas_width)
        self.camera.height = max(1, self.screen.get_height())

    def lod(self):
        """(level, block): cells are merged into block x block groups so each is at least min_cell_px at the target."""
        self._sync_viewport()
        pixels_per_cell = CELL_RESOLUTION * self.camera.focal_px / self.camera.distance
        level, block = 0, 1
        while pixels_per_cell * block < self.dimensions.min_cell_px and block < 2048:
            block *= 2
            level += 1
        return level, block

    # ── Picking ─────────────────────────────────────────────────────────────────
    def pick(self, screen_x, screen_y, heights) -> Pick | None:
        """
        Cast the ray through a pixel into the heightmap `heights` (cell -> height m).
        Returns the first obstacle column the ray enters (top or side), else the ground cell, else None (sky).
        Uses a 2D Amanatides-Woo grid walk, starting where the ray drops below the tallest obstacle.
        """
        self._sync_viewport()
        origin, direction = self.camera.ray(screen_x, screen_y)
        origin_x, origin_y, origin_z = (float(v) for v in origin)
        dir_x, dir_y, dir_z = (float(v) for v in direction)
        resolution = CELL_RESOLUTION

        ground_t = -origin_z / dir_z if dir_z < -1e-12 else math.inf
        max_height = max(heights.values(), default=0.0)

        def ground_pick():
            if math.isinf(ground_t):
                return None
            x, y = origin_x + dir_x * ground_t, origin_y + dir_y * ground_t
            return Pick((math.floor(x / resolution), math.floor(y / resolution)), (x, y, 0.0), 0.0)

        if max_height <= 0.0:
            return ground_pick()
        if origin_z <= max_height:
            start_t = 0.0
        elif dir_z < -1e-12:
            start_t = (max_height - origin_z) / dir_z
        else:
            return None   # Above every obstacle and looking up
        end_t = ground_t if not math.isinf(ground_t) else start_t + 1e4

        start_x, start_y = origin_x + dir_x * start_t, origin_y + dir_y * start_t
        cell_x, cell_y = math.floor(start_x / resolution), math.floor(start_y / resolution)

        def axis(start, direction_component, cell):
            if abs(direction_component) < 1e-12:
                return 0, math.inf, math.inf
            step = 1 if direction_component > 0 else -1
            boundary = (cell + 1) * resolution if step > 0 else cell * resolution
            return step, start_t + (boundary - start) / direction_component, resolution / abs(direction_component)

        step_x, next_x, spacing_x = axis(start_x, dir_x, cell_x)
        step_y, next_y, spacing_y = axis(start_y, dir_y, cell_y)

        enter_t = start_t
        for _ in range(MAX_PICK_STEPS):
            exit_t = min(next_x, next_y, end_t)
            height = heights.get((cell_x, cell_y))
            if height is not None:
                enter_z = origin_z + dir_z * enter_t
                exit_z = origin_z + dir_z * exit_t
                if min(enter_z, exit_z) <= height:
                    hit_t = enter_t if enter_z <= height else (height - origin_z) / dir_z
                    return Pick((cell_x, cell_y),
                                (origin_x + dir_x * hit_t, origin_y + dir_y * hit_t, origin_z + dir_z * hit_t),
                                height)
            if exit_t >= end_t:
                break
            if next_x < next_y:
                cell_x += step_x
                next_x += spacing_x
            else:
                cell_y += step_y
                next_y += spacing_y
            enter_t = exit_t
        return ground_pick()

    # ── Mesh building ───────────────────────────────────────────────────────────
    def _build_meshes(self, obstacles, lane_lines, block):
        size = CELL_RESOLUTION * block

        merged: dict[tuple[int, int], float] = {}
        for (cell_x, cell_y), height in obstacles.items():
            key = (cell_x // block, cell_y // block)
            if merged.get(key, 0.0) < height:
                merged[key] = height

        quads, normals, colors = [], [], []

        # Top faces, merged along rows of equal height (runs capped so depth sorting stays sensible)
        rows: dict[int, list[tuple[int, float]]] = {}
        for (block_x, block_y), height in merged.items():
            rows.setdefault(block_y, []).append((block_x, height))
        for block_y, items in rows.items():
            items.sort()
            run_start, run_end, run_height = items[0][0], items[0][0], items[0][1]
            for block_x, height in items[1:] + [(None, None)]:
                if block_x == run_end + 1 and height == run_height and run_end - run_start + 1 < MAX_TOP_RUN:
                    run_end = block_x
                    continue
                x0, x1 = run_start * size, (run_end + 1) * size
                y0, y1 = block_y * size, (block_y + 1) * size
                quads.append(((x0, y0, run_height), (x1, y0, run_height), (x1, y1, run_height), (x0, y1, run_height)))
                normals.append((0.0, 0.0, 1.0))
                colors.append(_shade(_lighten(height_color(run_height), LIGHTEN_3D), TOP_SHADE))
                if block_x is not None:
                    run_start, run_end, run_height = block_x, block_x, height

        # Side faces, only where the neighbour column is lower. Faces in the same plane with the same vertical
        # extent are merged along the wall (x faces run along y, y faces run along x).
        side_runs: dict[tuple, list[int]] = {}
        for (block_x, block_y), height in merged.items():
            for dx, dy in SIDE_SHADES:
                low = merged.get((block_x + dx, block_y + dy), 0.0)
                if low >= height:
                    continue
                if dx:
                    side_runs.setdefault((dx, dy, block_x, low, height), []).append(block_y)
                else:
                    side_runs.setdefault((dx, dy, block_y, low, height), []).append(block_x)
        for (dx, dy, fixed, low, height), positions in side_runs.items():
            color = _shade(_lighten(height_color(height), LIGHTEN_3D), SIDE_SHADES[(dx, dy)])
            positions.sort()
            index = 0
            while index < len(positions):
                run_start = run_end = positions[index]
                while (index + 1 < len(positions) and positions[index + 1] == run_end + 1
                       and run_end - run_start + 1 < MAX_TOP_RUN):
                    index += 1
                    run_end += 1
                index += 1
                a0, a1 = run_start * size, (run_end + 1) * size
                if dx == 1:
                    x = (fixed + 1) * size
                    quad = ((x, a0, low), (x, a1, low), (x, a1, height), (x, a0, height))
                elif dx == -1:
                    x = fixed * size
                    quad = ((x, a1, low), (x, a0, low), (x, a0, height), (x, a1, height))
                elif dy == 1:
                    y = (fixed + 1) * size
                    quad = ((a1, y, low), (a0, y, low), (a0, y, height), (a1, y, height))
                else:
                    y = fixed * size
                    quad = ((a0, y, low), (a1, y, low), (a1, y, height), (a0, y, height))
                quads.append(quad)
                normals.append((float(dx), float(dy), 0.0))
                colors.append(color)

        if quads:
            vertices = np.array(quads, dtype=np.float64)
            self._obstacle_mesh = (vertices, np.array(normals), vertices.mean(axis=1), colors,
                                   [_shade(color, EDGE_SHADE) for color in colors])
        else:
            self._obstacle_mesh = None

        # Lane lines: flat quads on the ground, merged along rows
        lane_blocks = sorted({(cell_y // block, cell_x // block) for cell_x, cell_y in lane_lines})
        lane_quads = []
        index = 0
        while index < len(lane_blocks):
            block_y, run_start = lane_blocks[index]
            run_end = run_start
            while index + 1 < len(lane_blocks) and lane_blocks[index + 1] == (block_y, run_end + 1):
                index += 1
                run_end += 1
            x0, x1 = run_start * size, (run_end + 1) * size
            y0, y1 = block_y * size, (block_y + 1) * size
            lane_quads.append(((x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)))
            index += 1
        self._lane_mesh = np.array(lane_quads, dtype=np.float64) if lane_quads else None

        self._mesh_block = block
        self._map_dirty = False

    # ── Rendering ───────────────────────────────────────────────────────────────
    def _project_quads(self, vertices):
        """Project (F, 4, 3) quads. Returns (screen points (F, 4, 2), in-front mask (F,))."""
        eye, right, up, forward = self.camera.basis()
        offsets = vertices - eye
        depth = offsets @ forward
        in_front = (depth > NEAR_PLANE_M).all(axis=1)
        safe_depth = np.where(depth > NEAR_PLANE_M, depth, NEAR_PLANE_M)
        focal = self.camera.focal_px
        screen_x = self.camera.width / 2 + focal * (offsets @ right) / safe_depth
        screen_y = self.camera.height / 2 - focal * (offsets @ up) / safe_depth
        points = np.clip(np.stack((screen_x, screen_y), axis=-1), -1e6, 1e6)
        return points, in_front

    def _on_screen(self, points):
        width, height = self.camera.width, self.camera.height
        return ((points[:, :, 0].max(axis=1) >= 0) & (points[:, :, 0].min(axis=1) <= width)
                & (points[:, :, 1].max(axis=1) >= 0) & (points[:, :, 1].min(axis=1) <= height))

    def _project_segment(self, start, end, eye, right, up, forward):
        """Clip a world segment to the near plane and project it, or return None."""
        start_offset, end_offset = np.asarray(start) - eye, np.asarray(end) - eye
        start_depth, end_depth = float(start_offset @ forward), float(end_offset @ forward)
        if start_depth < NEAR_PLANE_M and end_depth < NEAR_PLANE_M:
            return None
        if start_depth < NEAR_PLANE_M or end_depth < NEAR_PLANE_M:
            t = (NEAR_PLANE_M - start_depth) / (end_depth - start_depth)
            clipped = start_offset + (end_offset - start_offset) * t
            if start_depth < NEAR_PLANE_M:
                start_offset, start_depth = clipped, NEAR_PLANE_M
            else:
                end_offset, end_depth = clipped, NEAR_PLANE_M
        focal = self.camera.focal_px
        center_x, center_y = self.camera.width / 2, self.camera.height / 2

        def to_screen(offset, depth):
            return (max(-1e6, min(1e6, center_x + focal * float(offset @ right) / depth)),
                    max(-1e6, min(1e6, center_y - focal * float(offset @ up) / depth)))
        # Clip to the viewport: pygame rasterizes the full length of very long off-screen lines
        clipped = pygame.Rect(0, 0, self.camera.width, self.camera.height).clipline(
            to_screen(start_offset, start_depth), to_screen(end_offset, end_depth))
        return clipped or None

    def _draw_ground_grid(self, surface):
        eye, right, up, forward = self.camera.basis()
        camera = self.camera

        # Minor spacing: smallest power-of-ten multiple of a cell that is at least ~8 px apart at the target
        min_spacing_px = 8 * self.dimensions.scale
        spacing_cells = 1
        while spacing_cells * CELL_RESOLUTION * camera.focal_px / camera.distance < min_spacing_px and spacing_cells < 10**6:
            spacing_cells *= 10
        spacing = spacing_cells * CELL_RESOLUTION
        half_extent = min(camera.distance * 3, 100 * spacing)
        line_width = self.dimensions.grid_line_width

        first_x = math.floor((camera.target_x - half_extent) / spacing)
        last_x = math.ceil((camera.target_x + half_extent) / spacing)
        first_y = math.floor((camera.target_y - half_extent) / spacing)
        last_y = math.ceil((camera.target_y + half_extent) / spacing)
        y_min, y_max = first_y * spacing, last_y * spacing
        x_min, x_max = first_x * spacing, last_x * spacing

        def color_for(index):
            cell_index = index * spacing_cells
            if cell_index % SUPER_EVERY == 0:
                return GRID_SUPER
            if cell_index % MAJOR_EVERY == 0:
                return GRID_MAJOR
            return GRID_MINOR

        for index in range(first_x, last_x + 1):
            x = index * spacing
            segment = self._project_segment((x, y_min, 0.0), (x, y_max, 0.0), eye, right, up, forward)
            if segment:
                pygame.draw.line(surface, color_for(index), segment[0], segment[1], line_width)
        for index in range(first_y, last_y + 1):
            y = index * spacing
            segment = self._project_segment((x_min, y, 0.0), (x_max, y, 0.0), eye, right, up, forward)
            if segment:
                pygame.draw.line(surface, color_for(index), segment[0], segment[1], line_width)

        # Axes through the origin, if they cross the drawn area
        axis_width = self.dimensions.axis_line_width
        if y_min <= 0 <= y_max:
            segment = self._project_segment((x_min, 0.0, 0.0), (x_max, 0.0, 0.0), eye, right, up, forward)
            if segment:
                pygame.draw.line(surface, AXIS_COLOR, segment[0], segment[1], axis_width)
        if x_min <= 0 <= x_max:
            segment = self._project_segment((0.0, y_min, 0.0), (0.0, y_max, 0.0), eye, right, up, forward)
            if segment:
                pygame.draw.line(surface, AXIS_COLOR, segment[0], segment[1], axis_width)

    def _render_scene(self, surface, block):
        surface.fill(BACKGROUND_COLOR)
        self._draw_ground_grid(surface)

        # Lane lines lie on the ground, so they go under every obstacle and need no sorting
        if self._lane_mesh is not None:
            points, in_front = self._project_quads(self._lane_mesh)
            for quad in points[in_front & self._on_screen(points)].tolist():
                pygame.draw.polygon(surface, LANE_LINE_COLOR, quad)

        if self._obstacle_mesh is None:
            return
        vertices, normals, centers, colors, edge_colors = self._obstacle_mesh
        eye, _, _, _ = self.camera.basis()
        points, in_front = self._project_quads(vertices)
        facing = ((eye - centers) * normals).sum(axis=1) > 0
        visible = np.nonzero(in_front & facing & self._on_screen(points))[0]
        depth = ((centers[visible] - eye) ** 2).sum(axis=1)
        order = visible[np.argsort(-depth)]

        draw_edges = CELL_RESOLUTION * block * self.camera.focal_px / self.camera.distance >= 6
        screen_points = points.tolist()
        for face in order.tolist():
            quad = screen_points[face]
            pygame.draw.polygon(surface, colors[face], quad)
            if draw_edges:
                pygame.draw.polygon(surface, edge_colors[face], quad, 1)

    def draw_scene(self, obstacles, lane_lines):
        """Draw the 3D scene into the canvas area, re-rendering only if something changed."""
        self._sync_viewport()
        _, block = self.lod()
        if self._map_dirty or block != self._mesh_block:
            self._build_meshes(obstacles, lane_lines, block)
            self._scene_key = None

        size = (self.camera.width, self.camera.height)
        if self._scene is None or self._scene.get_size() != size:
            self._scene = pygame.Surface(size)
            self._scene_key = None

        key = self.camera.state()
        if key != self._scene_key:
            self._render_scene(self._scene, block)
            self._scene_key = key
        self.screen.blit(self._scene, (0, 0))
