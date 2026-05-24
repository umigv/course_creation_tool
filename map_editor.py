#!/usr/bin/env python3
"""
Map Editor — draw obstacles on a grid, place goal points.
Requires:  pip install pygame

Each grid cell is exactly 0.05 m (5 cm) and is indivisible.
When zooming out, cells are merged in powers of 2 (2x2, 4x4, 8x8 ...)
so the display always shows whole cells — never sub-cell rendering.

Controls:
  LMB drag        -> paint obstacles           (Draw mode)
  RMB drag        -> erase obstacles           (Draw mode)
  LMB click       -> place goal               (Goal mode)
  Shift+LMB click -> place no man's land goal (Goal mode)
  RMB click       -> remove nearest goal      (Goal mode)
  MMB drag        -> pan camera
  Alt+LMB drag    -> pan camera (laptop-friendly)
  Scroll wheel    -> zoom in / out
  Tab             -> toggle Draw / Goal mode
  [ / ]           -> shrink / grow brush
  Ctrl+Z          -> undo
  Ctrl+Y          -> redo
  S               -> save  (quick-save to current folder, else prompts)
  Ctrl+S          -> save-as (always prompts for folder)
  L               -> load (prompts for course folder)
  R               -> reset view to origin
  Delete          -> clear all
"""

import math, json, os, sys, subprocess
from dataclasses import dataclass

DATUM_LATITUDE = 42.294621
DATUM_LONGITUDE = -83.708112
DATUM_ALTITUDE = 270.0
EARTH_RADIUS   = 6378137.0
import pygame
import argparse
from map_renderer_base import MapRendererBase, BACKGROUND_COLOR, CELL_RESOLUTION, DEFAULT_PPM
from dpi_utils import setup_pygame_dpi_awareness


# ── Additional Palette for Editor ────────────────────────────────────────────
GOAL_FILL      = (240,  65,  65)
GOAL_RING      = (170,   0,   0)
NO_MANS_LAND_FILL       = (180,  80, 220)
NO_MANS_LAND_RING       = (110,  30, 160)
PANEL_BACKGROUND       = ( 32,  36,  48)
PANEL_FOREGROUND       = (218, 224, 238)
PANEL_DIMMED      = (110, 118, 140)
PANEL_SEPARATOR      = ( 55,  62,  78)
BUTTON_ACTIVE     = ( 72, 136, 255)
BUTTON_IDLE       = ( 58,  64,  82)
BUTTON_HOVER      = ( 80,  88, 110)
BRUSH_DRAW     = ( 72, 108, 230, 100)
BRUSH_ERASE    = (230,  72,  72, 100)
BRUSH_LANE     = (210, 170,  35, 100)
SCALE_COLOR      = ( 55,  58,  80)

# ── Constants ──────────────────────────────────────────────────────────────────
PANEL_WIDTH      = 240
MODE_DRAW    = "draw"
MODE_LANE    = "lane"
MODE_GOAL    = "goal"


@dataclass(frozen=True)
class Goal:
    x: float
    y: float
    no_mans_land: bool = False
    is_local: bool = False


@dataclass(frozen=True)
class HistoryEntry:
    obstacles: frozenset
    lane_lines: frozenset
    goals: tuple


def _dump_compact_arrays(obj, indent=2):
    """
    JSON-serialize a dict with pretty-printed fields but inline arrays.
    
    Useful for preventing very large diffs while still maintaining readability.
    """
    lines = ["{"]
    items = list(obj.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f'{" " * indent}{json.dumps(k)}: {json.dumps(v)}{comma}')
    lines.append("}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Native GTK file dialogs (Ubuntu 22)
# ─────────────────────────────────────────────────────────────────────────────
def _zenity(*args):
    """Run zenity, pumping pygame events so X11 stays alive and zenity gets focus."""
    import pygame
    try:
        proc = subprocess.Popen(["zenity", *args],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return None, -1
    while proc.poll() is None:
        pygame.event.pump()
        pygame.time.wait(30)
    stdout, _ = proc.communicate()
    return stdout.decode().strip(), proc.returncode


def _native_folder_dialog(title="Select course folder", initial_dir=None):
    command = ["--file-selection", "--directory", "--title", title]
    if initial_dir and os.path.isdir(initial_dir):
        command += ["--filename", initial_dir.rstrip("/") + "/"]
    text, code = _zenity(*command)
    return text or None if code == 0 else None


def _native_error(title, message):
    _zenity("--error", "--no-wrap", "--title", title, "--text", message)


# ─────────────────────────────────────────────────────────────────────────────
# Button widget
# ─────────────────────────────────────────────────────────────────────────────
class Button:
    def __init__(self, rect, label, active=False, color_active=None):
        self.rect        = pygame.Rect(rect)
        self.label       = label
        self.active      = active
        self.hover       = False
        self._color_active = color_active or BUTTON_ACTIVE

    def draw(self, surf, font):
        color = self._color_active if self.active else (BUTTON_HOVER if self.hover else BUTTON_IDLE)
        pygame.draw.rect(surf, color, self.rect, border_radius=7)
        txt = font.render(self.label, True, PANEL_FOREGROUND)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def update(self, mouse_pos): self.hover = self.rect.collidepoint(mouse_pos)
    def hit(self, event):
        return (event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and self.rect.collidepoint(event.pos))


# ─────────────────────────────────────────────────────────────────────────────
# Renderer subclass for editor with panel offset
# ─────────────────────────────────────────────────────────────────────────────
class EditorRenderer(MapRendererBase):
    """
    Extends MapRendererBase to handle the right-side panel offset.
    The canvas is (W - PANEL_WIDTH) wide, and coordinates are adjusted accordingly.
    """
    
    def __init__(self, screen, canvas_width, initial_ppm=DEFAULT_PPM, scale_factor=1.0):
        super().__init__(screen, initial_ppm, scale_factor)
        self.canvas_width = canvas_width
    
    def world_to_screen(self, world_x, world_y):
        """Override to use canvas_width instead of full screen width"""
        screen_width, screen_height = self.screen.get_size()
        screen_x = (world_x - self.camera_x) * self.ppm + self.canvas_width / 2
        screen_y = -(world_y - self.camera_y) * self.ppm + screen_height / 2  # Negate Y for screen coords
        return screen_x, screen_y
    
    def screen_to_world(self, screen_x, screen_y):
        """Override to use canvas_width instead of full screen width"""
        screen_width, screen_height = self.screen.get_size()
        world_x = (screen_x - self.canvas_width / 2) / self.ppm + self.camera_x
        world_y = -(screen_y - screen_height / 2) / self.ppm + self.camera_y  # Negate Y for world coords
        return world_x, world_y
    
    def draw_grid(self):
        """Override to clip grid to canvas area"""
        screen_width, screen_height = self.screen.get_size()
        _, block = self._lod()
        
        # Calculate grid range - only for canvas area
        top_left_x, top_left_y = self.screen_to_world(0, 0)
        top_right_x, top_right_y = self.screen_to_world(self.canvas_width, 0)
        bottom_left_x, bottom_left_y = self.screen_to_world(0, screen_height)
        bottom_right_x, bottom_right_y = self.screen_to_world(self.canvas_width, screen_height)
        
        x_min = min(top_left_x, top_right_x, bottom_left_x, bottom_right_x)
        x_max = max(top_left_x, top_right_x, bottom_left_x, bottom_right_x)
        y_min = min(top_left_y, top_right_y, bottom_left_y, bottom_right_y)
        y_max = max(top_left_y, top_right_y, bottom_left_y, bottom_right_y)
        
        from map_renderer_base import GRID_MINOR, GRID_MAJOR, GRID_SUPER, AXIS_COLOR, SUPER_EVERY, MAJOR_EVERY
        
        grid_size = CELL_RESOLUTION * block
        start_x = math.floor(x_min / grid_size) * grid_size
        start_y = math.floor(y_min / grid_size) * grid_size
        
        grid_line_width = self.dimensions.grid_line_width
        
        # Vertical lines
        x = start_x
        while x <= x_max:
            screen_x, _ = self.world_to_screen(x, 0)
            cell_idx = int(round(x / CELL_RESOLUTION))
            if cell_idx % (SUPER_EVERY * block) == 0:
                color = GRID_SUPER
            elif cell_idx % (MAJOR_EVERY * block) == 0:
                color = GRID_MAJOR
            else:
                color = GRID_MINOR
            if 0 <= screen_x <= self.canvas_width:
                pygame.draw.line(self.screen, color, (screen_x, 0), (screen_x, screen_height), grid_line_width)
            x += grid_size
        
        # Horizontal lines
        y = start_y
        while y <= y_max:
            _, screen_y = self.world_to_screen(0, y)
            cell_idx = int(round(y / CELL_RESOLUTION))
            if cell_idx % (SUPER_EVERY * block) == 0:
                color = GRID_SUPER
            elif cell_idx % (MAJOR_EVERY * block) == 0:
                color = GRID_MAJOR
            else:
                color = GRID_MINOR
            pygame.draw.line(self.screen, color, (0, screen_y), (self.canvas_width, screen_y), grid_line_width)
            y += grid_size
        
        # Draw axes (clipped to canvas)
        x0, _ = self.world_to_screen(0, 0)
        _, y0 = self.world_to_screen(0, 0)
        axis_line_width = self.dimensions.axis_line_width
        if 0 <= x0 <= self.canvas_width:
            pygame.draw.line(self.screen, AXIS_COLOR, (x0, 0), (x0, screen_height), axis_line_width)
        if 0 <= y0 <= screen_height:
            pygame.draw.line(self.screen, AXIS_COLOR, (0, y0), (self.canvas_width, y0), axis_line_width)


# ─────────────────────────────────────────────────────────────────────────────
# Main editor
# ─────────────────────────────────────────────────────────────────────────────
class MapEditor:
    def __init__(self, width=1340, height=820):
        # Setup DPI awareness before pygame.init()
        scale_factor = setup_pygame_dpi_awareness()
        pygame.init()
        
        # Apply scale factor to window size
        self.scale_factor = scale_factor
        self.width, self.height = int(width * scale_factor), int(height * scale_factor)
        self.canvas_width  = self.width - int(PANEL_WIDTH * scale_factor)
        self.screen    = pygame.display.set_mode((self.width, self.height), pygame.RESIZABLE)
        pygame.display.set_caption("Map Editor  |  5 cm / cell")

        # Scale fonts based on DPI
        font_size_small = max(11, int(13 * scale_factor))
        font_size_medium = max(13, int(15 * scale_factor))
        font_size_large = max(15, int(18 * scale_factor))
        
        self.font_small = pygame.font.SysFont("monospace", font_size_small)
        self.font_medium = pygame.font.SysFont("monospace", font_size_medium, bold=True)
        self.font_large = pygame.font.SysFont("monospace", font_size_large, bold=True)
        self.clock  = pygame.time.Clock()

        # Initialize renderer
        self.renderer = EditorRenderer(self.screen, self.canvas_width, DEFAULT_PPM, scale_factor)

        self.goals: list[Goal] = []

        self.mode          = MODE_DRAW
        self.brush_radius   = 1
        self.drawing       = False
        self.erasing       = False
        self._last_paint_pos: tuple | None = None   # for stroke interpolation
        self.current_file  = None
        self.status_msg    = ""
        self.status_timer  = 0

        # Undo / redo stacks
        self._undo_stack: list[HistoryEntry] = []
        self._redo_stack: list[HistoryEntry] = []
        self._MAX_HISTORY = 64
        
        # UI Scale slider
        self.base_scale_factor = scale_factor  # Store original detected scale
        self.scale_slider_dragging = False
        self.scale_slider_preview = None  # Preview scale while dragging
        
        # Panel scrolling
        self.panel_scroll_offset = 0  # Current scroll position
        self.panel_content_height = 0  # Total height of panel content
        self.scrollbar_dragging = False
        self.scrollbar_drag_start_y = 0
        self.scrollbar_drag_start_scroll = 0

        self._build_ui()
    
    @property
    def current_scale(self):
        """Get current UI scale (dynamic, from slider)"""
        return self.renderer.dimensions.scale
    
    def _get_ui_scale(self):
        """Get current UI scale factor for layout calculations"""
        return self.renderer.dimensions.scale

    # ── Coordinates ────────────────────────────────────────────────────────────
    def _update_fonts(self):
        """Recreate fonts with current scale"""
        font_size_small = max(11, int(13 * self.renderer.dimensions.scale))
        font_size_medium = max(13, int(15 * self.renderer.dimensions.scale))
        font_size_large = max(15, int(18 * self.renderer.dimensions.scale))

        self.font_small = pygame.font.SysFont("monospace", font_size_small)
        self.font_medium = pygame.font.SysFont("monospace", font_size_medium, bold=True)
        self.font_large = pygame.font.SysFont("monospace", font_size_large, bold=True)
    
    def world_to_base_cell(self, world_x, world_y):
        """Convert world coordinates to cell indices (cell_x, cell_y)"""
        return (int(math.floor(world_x / CELL_RESOLUTION)),
                int(math.floor(world_y / CELL_RESOLUTION)))

    # ── Edit operations ────────────────────────────────────────────────────────
    def _stamp(self, screen_x, screen_y, erase=False):
        """Stamp the brush once at screen position (screen_x, screen_y)."""
        world_x, world_y = self.renderer.screen_to_world(screen_x, screen_y)
        cell_x, cell_y = self.world_to_base_cell(world_x, world_y)
        target = self.renderer.lane_lines if self.mode == MODE_LANE else self.renderer.obstacles
        for dx in range(-self.brush_radius, self.brush_radius + 1):
            for dy in range(-self.brush_radius, self.brush_radius + 1):
                if dx * dx + dy * dy <= self.brush_radius * self.brush_radius:
                    key = (cell_x + dx, cell_y + dy)
                    if erase:
                        target.discard(key)
                    else:
                        target.add(key)

    def paint(self, screen_x, screen_y, erase=False):
        """Paint from the last position to (screen_x, screen_y), interpolating to fill gaps."""
        if self._last_paint_pos is None:
            self._stamp(screen_x, screen_y, erase)
        else:
            x0, y0 = self._last_paint_pos
            dx, dy = screen_x - x0, screen_y - y0
            dist = math.hypot(dx, dy)
            # Step at most half a cell-width so no cell is ever skipped
            step = max(1.0, CELL_RESOLUTION * self.renderer.ppm * 0.5)
            steps = max(1, int(dist / step))
            for i in range(steps + 1):
                t = i / steps
                self._stamp(x0 + dx * t, y0 + dy * t, erase)
        self._last_paint_pos = (screen_x, screen_y)

    def place_goal(self, screen_x, screen_y, no_mans_land=False):
        world_x, world_y = self.renderer.screen_to_world(screen_x, screen_y)
        is_local = bool(self.goals) and all(g.is_local for g in self.goals)
        self.goals.append(Goal(world_x, world_y, no_mans_land, is_local))

    def remove_nearest_goal(self, screen_x, screen_y):
        if not self.goals: return
        world_x, world_y    = self.renderer.screen_to_world(screen_x, screen_y)
        threshold = 25 / self.renderer.ppm
        idx = min(range(len(self.goals)),
                  key=lambda i: (self.goals[i].x - world_x)**2 + (self.goals[i].y - world_y)**2)
        if math.hypot(self.goals[idx].x - world_x, self.goals[idx].y - world_y) <= threshold:
            self.goals.pop(idx)

    # ── File I/O ────────────────────────────────────────────────────────────────
    def _goal_to_waypoint(self, goal_x, goal_y):
        lat = DATUM_LATITUDE + (goal_y / EARTH_RADIUS) * (180.0 / math.pi)
        lon = DATUM_LONGITUDE + (goal_x / (EARTH_RADIUS * math.cos(math.radians(DATUM_LATITUDE)))) * (180.0 / math.pi)
        return {"latitude": lat, "longitude": lon}

    def _waypoint_to_goal(self, waypoint, datum=None):
        if "x" in waypoint and "y" in waypoint:
            return (float(waypoint["x"]), float(waypoint["y"]))
        datum_lat = datum["latitude"]  if datum else DATUM_LATITUDE
        datum_lon = datum["longitude"] if datum else DATUM_LONGITUDE
        goal_y = (waypoint["latitude"]  - datum_lat) * (math.pi / 180.0) * EARTH_RADIUS
        goal_x = (waypoint["longitude"] - datum_lon) * (math.pi / 180.0) * EARTH_RADIUS * math.cos(math.radians(datum_lat))
        return (goal_x, goal_y)

    def _load_gps_json(self, map_path):
        gps_path = os.path.join(os.path.dirname(os.path.abspath(map_path)), "gps.json")
        if not os.path.isfile(gps_path):
            return
        try:
            with open(gps_path) as f:
                data = json.load(f)
        except Exception:
            return
        waypoints = data.get("waypoints", [])
        datum = data.get("datum")
        self.goals = [
            Goal(*self._waypoint_to_goal(waypoint, datum), waypoint.get("no_mans_land", False), "x" in waypoint)
            for waypoint in waypoints
        ]

    def _save_gps_json(self, map_path):
        gps_path = os.path.join(os.path.dirname(os.path.abspath(map_path)), "gps.json")
        waypoints = []
        for goal in self.goals:
            if goal.is_local:
                waypoint = {"x": goal.x, "y": goal.y}
            else:
                waypoint = self._goal_to_waypoint(goal.x, goal.y)
            if goal.no_mans_land:
                waypoint["no_mans_land"] = True
            waypoints.append(waypoint)
        data = {
            "datum": {"latitude": DATUM_LATITUDE, "longitude": DATUM_LONGITUDE, "altitude": DATUM_ALTITUDE},
            "waypoints": waypoints,
        }
        with open(gps_path, "w") as f:
            json.dump(data, f, indent=4)

    def _course_dir(self):
        """Return the directory of the current course, or cwd if none loaded."""
        if self.current_file:
            return os.path.dirname(os.path.abspath(self.current_file))
        return os.getcwd()

    def _flush_input(self):
        """Discard queued events and reset paint state after a dialog steals focus."""
        self.drawing = False
        self.erasing = False
        self._last_paint_pos = None
        pygame.event.clear()

    def save(self, folder=None, force_dialog=False):
        if folder is None or force_dialog:
            folder = _native_folder_dialog("Select course folder to save", self._course_dir())
            self._flush_input()
            if folder is None:
                return
        elif os.path.isfile(folder):
            folder = os.path.dirname(os.path.abspath(folder))

        path = os.path.join(folder, "map.json")
        try:
            data = {
                "resolution_m": CELL_RESOLUTION,
                "obstacles":    [list(obstacle_cell) for obstacle_cell in self.renderer.obstacles],
                "lane_lines":   [list(lane_line_cell) for lane_line_cell in self.renderer.lane_lines],
            }
            with open(path, "w") as f:
                f.write(_dump_compact_arrays(data))
            self._save_gps_json(path)
            self.current_file = path
            self._status(f"Saved -> {os.path.basename(folder)}/")
        except OSError as e:
            _native_error("Save failed", str(e))

    def load(self, path=None):
        if path is None:
            folder = _native_folder_dialog("Select course folder to load", self._course_dir())
            self._flush_input()
            if folder is None:
                return
            path = os.path.join(folder, "map.json")
        elif os.path.isdir(path):
            path = os.path.join(path, "map.json")

        if not os.path.isfile(path):
            _native_error("map.json not found", f"No map.json in:\n{os.path.dirname(path)}")
            return

        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            _native_error("Load failed", str(e))
            return

        saved_cm = float(data.get("resolution_m", CELL_RESOLUTION))
        scale    = max(1, round(saved_cm / CELL_RESOLUTION))

        self.renderer.obstacles = set()
        for o in data.get("obstacles", []):
            x0, y0 = int(o[0]), int(o[1])
            for dx in range(scale):
                for dy in range(scale):
                    self.renderer.obstacles.add((x0*scale + dx, y0*scale + dy))

        self.renderer.lane_lines = set()
        for l in data.get("lane_lines", []):
            x0, y0 = int(l[0]), int(l[1])
            for dx in range(scale):
                for dy in range(scale):
                    self.renderer.lane_lines.add((x0*scale + dx, y0*scale + dy))

        self._load_gps_json(path)
        self.current_file = path
        self._status(f"Loaded <- {os.path.basename(os.path.dirname(path))}/")

    def _status(self, msg, secs=3.0):
        self.status_msg   = msg
        self.status_timer = int(secs * 60)

    # ── Undo / redo ─────────────────────────────────────────────────────────────
    def _push_history(self):
        """Save current state onto the undo stack and clear the redo stack."""
        entry = HistoryEntry(frozenset(self.renderer.obstacles), frozenset(self.renderer.lane_lines), tuple(self.goals))
        if self._undo_stack and self._undo_stack[-1] == entry:
            return  # nothing changed — don't create a duplicate entry
        self._undo_stack.append(entry)
        if len(self._undo_stack) > self._MAX_HISTORY:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore(self, entry: HistoryEntry):
        self.renderer.obstacles  = set(entry.obstacles)
        self.renderer.lane_lines = set(entry.lane_lines)
        self.goals = list(entry.goals)

    def _current_state(self) -> HistoryEntry:
        return HistoryEntry(frozenset(self.renderer.obstacles), frozenset(self.renderer.lane_lines), tuple(self.goals))

    def undo(self):
        if not self._undo_stack:
            self._status("Nothing to undo.", 1.5); return
        self._redo_stack.append(self._current_state())
        self._restore(self._undo_stack.pop())
        self._status("Undo", 1.0)

    def redo(self):
        if not self._redo_stack:
            self._status("Nothing to redo.", 1.5); return
        self._undo_stack.append(self._current_state())
        self._restore(self._redo_stack.pop())
        self._status("Redo", 1.0)

    # ── Rendering ───────────────────────────────────────────────────────────────
    def draw(self):
        self.screen.fill(BACKGROUND_COLOR)
        self.renderer.draw_obstacles()
        self.renderer.draw_lane_lines()
        self._draw_goals()
        self._draw_brush_preview()
        self.renderer.draw_grid()  # Draw grid on top
        self._draw_scale_bar()
        self._draw_coords_lod()
        self._draw_status()
        self._draw_panel()
        pygame.display.flip()

    def _draw_goals(self):
        radius_px = max(7, min(26, CELL_RESOLUTION * 1.0 * self.renderer.ppm))
        radius_int = int(radius_px)
        for goal in self.goals:
            screen_x, screen_y = self.renderer.world_to_screen(goal.x, goal.y)
            si, sj = int(screen_x), int(screen_y)
            if -radius_int <= si <= self.canvas_width + radius_int and -radius_int <= sj <= self.height + radius_int:
                fill, ring = (NO_MANS_LAND_FILL, NO_MANS_LAND_RING) if goal.no_mans_land else (GOAL_FILL, GOAL_RING)
                pygame.draw.circle(self.screen, fill, (si, sj), radius_int)
                pygame.draw.circle(self.screen, ring, (si, sj), radius_int, 2)
                if goal.no_mans_land:
                    d = int(radius_int * 0.65)
                    pygame.draw.line(self.screen, ring, (si-d, sj-d), (si+d, sj+d), 2)
                    pygame.draw.line(self.screen, ring, (si+d, sj-d), (si-d, sj+d), 2)
                else:
                    pygame.draw.line(self.screen, ring, (si-radius_int, sj), (si+radius_int, sj), 2)
                    pygame.draw.line(self.screen, ring, (si, sj-radius_int), (si, sj+radius_int), 2)

    def _draw_brush_preview(self):
        mouse_x, mouse_y = pygame.mouse.get_pos()
        if mouse_x >= self.canvas_width: return
        if self.mode in (MODE_DRAW, MODE_LANE):
            radius_px = max(2, int((self.brush_radius + 0.5) * CELL_RESOLUTION * self.renderer.ppm))
            if self.erasing:
                fill_color, ring_color = BRUSH_ERASE, (200, 60, 60)
            elif self.mode == MODE_LANE:
                fill_color, ring_color = BRUSH_LANE, (180, 145, 25)
            else:
                fill_color, ring_color = BRUSH_DRAW, (60, 80, 200)
            surf = pygame.Surface((radius_px*2+4, radius_px*2+4), pygame.SRCALPHA)
            pygame.draw.circle(surf, fill_color, (radius_px+2, radius_px+2), radius_px)
            self.screen.blit(surf, (mouse_x-radius_px-2, mouse_y-radius_px-2))
            pygame.draw.circle(self.screen, ring_color, (mouse_x, mouse_y), radius_px, 1)
        else:
            radius_int = max(7, min(26, int(CELL_RESOLUTION * self.renderer.ppm)))
            pygame.draw.circle(self.screen, GOAL_FILL, (mouse_x, mouse_y), radius_int, 2)
            pygame.draw.line(self.screen, GOAL_FILL, (mouse_x-radius_int, mouse_y), (mouse_x+radius_int, mouse_y), 1)
            pygame.draw.line(self.screen, GOAL_FILL, (mouse_x, mouse_y-radius_int), (mouse_x, mouse_y+radius_int), 1)

    def _draw_scale_bar(self):
        target_px  = 160
        world_span = target_px / self.renderer.ppm
        magnitude  = 10 ** math.floor(math.log10(max(world_span, 1e-9)))
        nice_vals  = [0.1,0.2,0.5,1,2,5,10,20,50,100,200,500,1000]
        world_length  = magnitude
        for v in nice_vals:
            if v * magnitude >= world_span * 0.4:
                world_length = v * magnitude; break
        bar_px = int(world_length * self.renderer.ppm)
        bar_x, bar_y = 18, self.height - 38
        pygame.draw.rect(self.screen, SCALE_COLOR, (bar_x, bar_y, bar_px, 5))
        pygame.draw.line(self.screen, SCALE_COLOR, (bar_x, bar_y-5), (bar_x, bar_y+10), 2)
        pygame.draw.line(self.screen, SCALE_COLOR, (bar_x+bar_px, bar_y-5), (bar_x+bar_px, bar_y+10), 2)
        if world_length >= 1:   label = f"{world_length:.4g} m"
        elif world_length >= 0.01: label = f"{world_length*100:.4g} cm"
        else:                label = f"{world_length*1000:.4g} mm"
        txt = self.font_small.render(label, True, SCALE_COLOR)
        self.screen.blit(txt, (bar_x + bar_px//2 - txt.get_width()//2, bar_y+12))

    def _draw_coords_lod(self):
        level, block = self.renderer._lod()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        if mouse_x < self.canvas_width:
            world_x, world_y = self.renderer.screen_to_world(mouse_x, mouse_y)
            cell_x, cell_y = self.world_to_base_cell(world_x, world_y)
            txt = self.font_small.render(
                f"({world_x:+.4f}, {world_y:+.4f}) m   cell ({cell_x}, {cell_y})   LOD {level} ({block}x{block})",
                True, SCALE_COLOR)
            self.screen.blit(txt, (18, self.height - 60))

    def _draw_status(self):
        if self.status_timer > 0:
            self.status_timer -= 1
            surf = self.font_small.render(self.status_msg, True, (80, 200, 80))
            surf.set_alpha(min(255, self.status_timer * 6))
            self.screen.blit(surf, (18, self.height - 80))

    # ── Panel ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        ui_scale = self._get_ui_scale()
        panel_width = int(PANEL_WIDTH * ui_scale)
        panel_x = self.canvas_width + int(10 * ui_scale)
        button_width = panel_width - int(20 * ui_scale)
        half_width = (button_width - int(6 * ui_scale)) // 2

        self.button_draw   = Button((panel_x,  int(48 * ui_scale), button_width, int(36 * ui_scale)), "Draw Obstacles",  active=(self.mode==MODE_DRAW))
        self.button_lane   = Button((panel_x,  int(90 * ui_scale), button_width, int(36 * ui_scale)), "Draw Lane Lines", active=(self.mode==MODE_LANE),
                                 color_active=(180, 145, 25))
        self.button_goal   = Button((panel_x, int(132 * ui_scale), button_width, int(36 * ui_scale)), "Place Goals",     active=(self.mode==MODE_GOAL))

        # File operations — start AFTER the info-text block (separator at196, text 142-192)
        self.button_save   = Button((panel_x, int(204 * ui_scale), button_width, int(32 * ui_scale)), "Save")
        self.button_saveas = Button((panel_x, int(242 * ui_scale), button_width, int(32 * ui_scale)), "Save As...")
        self.button_load   = Button((panel_x, int(280 * ui_scale), button_width, int(32 * ui_scale)), "Load...")

        # Undo / Redo — after separator at320, "History" micro-label at 322
        self.button_undo   = Button((panel_x,                             int(338 * ui_scale), half_width, int(32 * ui_scale)), "↩  Undo")
        self.button_redo   = Button((panel_x + half_width + int(6 * ui_scale), int(338 * ui_scale), half_width, int(32 * ui_scale)), "Redo  ↪")

        # Danger zone — after separator at378
        self.button_clear  = Button((panel_x, int(386 * ui_scale), button_width, int(32 * ui_scale)), "Clear All",
                                 color_active=(200, 60, 60))

        self.buttons = [self.button_draw, self.button_lane, self.button_goal,
                        self.button_save, self.button_saveas, self.button_load,
                        self.button_undo, self.button_redo,
                        self.button_clear]

    def _draw_panel(self):
        ui_scale = self._get_ui_scale()
        panel_width = int(PANEL_WIDTH * ui_scale)
        mouse_pos = pygame.mouse.get_pos()
        
        # Draw panel background
        pygame.draw.rect(self.screen, PANEL_BACKGROUND, (self.canvas_width, 0, panel_width, self.height))
        pygame.draw.line(self.screen, PANEL_SEPARATOR, (self.canvas_width, 0), (self.canvas_width, self.height), 2)

        # Title (not scrolled)
        t = self.font_large.render("MAP  EDITOR", True, PANEL_FOREGROUND)
        self.screen.blit(t, (self.canvas_width + panel_width//2 - t.get_width()//2, int(14 * ui_scale)))

        # Buttons (not scrolled)
        self.button_draw.active = self.mode == MODE_DRAW
        self.button_lane.active = self.mode == MODE_LANE
        self.button_goal.active = self.mode == MODE_GOAL
        for button in self.buttons:
            button.update(mouse_pos)
            button.draw(self.screen, self.font_small)

        # Scrollable content starts after last button
        scrollable_start = self.button_clear.rect.bottom + int(10 * ui_scale)
        scrollable_height = self.height - scrollable_start
        
        # Create virtual surface for scrollable content
        virtual_h = max(4000, self.height * 2)
        virtual_surface = pygame.Surface((panel_width, virtual_h))
        virtual_surface.fill(PANEL_BACKGROUND)
        
        button_x_virtual = int(10 * ui_scale)
        button_x_screen = self.canvas_width + int(10 * ui_scale)
        y = 0
        
        # Helper functions drawing to virtual surface
        def draw_separator(spacing=8):
            nonlocal y
            y += int(spacing * ui_scale)
            pygame.draw.line(virtual_surface, PANEL_SEPARATOR,
                           (button_x_virtual, y), (panel_width - int(10 * ui_scale), y), 1)
            y += int(4 * ui_scale)

        def lbl(text, color=PANEL_FOREGROUND, spacing=0):
            nonlocal y
            y += int(spacing * ui_scale)
            small_text = self.font_small.render(text, True, color)
            virtual_surface.blit(small_text, (button_x_virtual, y))
            y += small_text.get_height() + int(2 * ui_scale)

        # Scrollable content starts here
        y = 0
        
        # Mode/brush info
        draw_separator(4)
        mode_label = {MODE_DRAW: "OBSTACLES", MODE_LANE: "LANE LINES", MODE_GOAL: "GOAL"}[self.mode]
        lbl(f"Mode  : {mode_label}")
        if self.mode in (MODE_DRAW, MODE_LANE):
            diameter_m = (self.brush_radius * 2 + 1) * CELL_RESOLUTION
            lbl(f"Brush : r={self.brush_radius} ({diameter_m:.2f} m diam)")
            lbl("  [ / ]  to resize", PANEL_DIMMED)

        # Stats
        draw_separator(8)
        lbl("-- Stats --", PANEL_DIMMED, 4)
        level, block = self.renderer._lod()
        lbl(f"LOD   : {level}  ({block}x{block} cells merged)")
        lbl(f"Display cell = {CELL_RESOLUTION*block*100:.4g} cm")
        lbl(f"Obstacles : {len(self.renderer.obstacles):,}")
        lbl(f"LaneLines : {len(self.renderer.lane_lines):,}")
        no_mans_land_count = sum(1 for g in self.goals if g.no_mans_land)
        lbl(f"Goals     : {len(self.goals)}  ({no_mans_land_count} No Man's Land)")
        lbl(f"Zoom      : {self.renderer.ppm:.1f} px/m")
        lbl(f"Base cell : {CELL_RESOLUTION*100:.0f} cm (fixed)")

        draw_separator(8)
        folder = os.path.basename(os.path.dirname(self.current_file)) if self.current_file else "(unsaved)"
        lbl(f"Folder: {folder}", PANEL_DIMMED)
        if not self.goals:
            gps_format = "(no waypoints)"
        elif all(g.is_local for g in self.goals):
            gps_format = "local (x/y)"
        elif any(g.is_local for g in self.goals):
            gps_format = "mixed"
        else:
            gps_format = "lat/lon"
        lbl(f"GPS : {gps_format}", PANEL_DIMMED)
        
        # UI Scale Slider
        draw_separator(8)
        display_scale = self.scale_slider_preview if self.scale_slider_preview is not None else self.renderer.dimensions.scale
        lbl(f"UI Scale: {display_scale:.2f}x", PANEL_DIMMED)
        
        slider_width = panel_width - int(40 * ui_scale)
        slider_x_virtual = button_x_virtual + int(10 * ui_scale)
        slider_y_virtual = y + int(4 * ui_scale)
        track_height = int(4 * ui_scale)
        
        pygame.draw.rect(virtual_surface, (60, 66, 85), 
                        pygame.Rect(slider_x_virtual, slider_y_virtual, slider_width, track_height), 
                        border_radius=2)
        
        scale_range = 3.0 - 0.5
        normalized = (display_scale - 0.5) / scale_range
        thumb_x = slider_x_virtual + int(normalized * slider_width)
        thumb_y = slider_y_virtual + track_height // 2
        thumb_radius = int(7 * ui_scale)
        
        thumb_color = (100, 150, 255) if self.scale_slider_dragging else BUTTON_ACTIVE
        pygame.draw.circle(virtual_surface, thumb_color, (thumb_x, thumb_y), thumb_radius)
        pygame.draw.circle(virtual_surface, PANEL_FOREGROUND, (thumb_x, thumb_y), thumb_radius - 2)
        
        # Store slider rect (adjusted for scroll and screen position)
        self._slider_rect = pygame.Rect(
            self.canvas_width + slider_x_virtual,
            scrollable_start + slider_y_virtual - self.panel_scroll_offset,
            slider_width, thumb_radius * 2
        )
        
        y = slider_y_virtual + int(20 * ui_scale)

        # Controls
        draw_separator(8)
        lbl("-- Controls --", PANEL_DIMMED, 4)
        
        controls = [
            ("LMB drag",  "Paint / Place goal"),
            ("Shift+LMB", "Place no man's land goal"),
            ("RMB drag",  "Erase / Remove goal"),
            ("MMB drag",  "Pan"),
            ("Alt+drag",  "Pan (laptop)"),
            ("Scroll",    "Zoom (canvas) / Scroll (panel)"),
            ("Slider",    "UI Scale"),
            ("[ / ]",     "Brush size"),
            ("Tab",       "Cycle mode (obs/lane/goal)"),
            ("Ctrl+Z/Y",  "Undo / Redo"),
            ("S",         "Save"),
            ("Ctrl+S",    "Save as..."),
            ("L",         "Load"),
            ("R",         "Reset view"),
            ("Del",       "Clear all"),
        ]
        
        for keybind, description in controls:
            keybind_text_rendered = self.font_small.render(f"{keybind:<10}", True, (160,185,255))
            desc_text_rendered = self.font_small.render(description, True, PANEL_DIMMED)
            virtual_surface.blit(keybind_text_rendered, (button_x_virtual, y))
            virtual_surface.blit(desc_text_rendered, (button_x_virtual + int(80 * ui_scale), y))
            y += self.font_small.get_height() + int(2 * ui_scale)
        
        # Store content height
        self.panel_content_height = y + int(20 * ui_scale)
        
        # Clamp scroll
        max_scroll = max(0, self.panel_content_height - scrollable_height)
        self.panel_scroll_offset = max(0, min(self.panel_scroll_offset, max_scroll))
        
        # Blit scrollable portion
        source_rect = pygame.Rect(0, self.panel_scroll_offset, panel_width, scrollable_height)
        self.screen.blit(virtual_surface, (self.canvas_width, scrollable_start), source_rect)
        
        # Draw scrollbar if needed
        if self.panel_content_height > scrollable_height:
            self._draw_scrollbar(panel_width, scrollable_start, scrollable_height)
    
    def _draw_scrollbar(self, panel_width, start_y, height):
        """Draw vertical scrollbar on panel"""
        ui_scale = self._get_ui_scale()
        scrollbar_w = int(8 * ui_scale)
        scrollbar_x = self.canvas_width + panel_width - scrollbar_w - int(4 * ui_scale)
        
        # Track
        track_rect = pygame.Rect(scrollbar_x, start_y, scrollbar_w, height)
        pygame.draw.rect(self.screen, (40, 44, 56), track_rect, border_radius=4)
        
        # Thumb
        if self.panel_content_height > height:
            thumb_height = max(int(30 * ui_scale), int(height * height / self.panel_content_height))
            scroll_ratio = self.panel_scroll_offset / max(1, self.panel_content_height - height)
            thumb_y = start_y + int(scroll_ratio * (height - thumb_height))
            
            thumb_rect = pygame.Rect(scrollbar_x, thumb_y, scrollbar_w, thumb_height)
            pygame.draw.rect(self.screen, (BUTTON_ACTIVE if self._is_scrollbar_hovered() else (80, 88, 110)), 
                           thumb_rect, border_radius=4)
    
    def _is_scrollbar_hovered(self):
        """Check if mouse is over scrollbar"""
        mouse_x, mouse_y = pygame.mouse.get_pos()
        ui_scale = self._get_ui_scale()
        panel_width = int(PANEL_WIDTH * ui_scale)
        scrollbar_w = int(8 * ui_scale)
        scrollbar_x = self.canvas_width + panel_width - scrollbar_w - int(4 * ui_scale)
        scrollable_start = self.button_clear.rect.bottom + int(10 * ui_scale)
        
        return (scrollbar_x <= mouse_x < scrollbar_x + scrollbar_w and 
                scrollable_start <= mouse_y < self.height)
    
    def _get_scrollbar_thumb_rect(self):
        """Get scrollbar thumb rect for interaction"""
        ui_scale = self._get_ui_scale()
        panel_width = int(PANEL_WIDTH * ui_scale)
        scrollbar_w = int(8 * ui_scale)
        scrollbar_x = self.canvas_width + panel_width - scrollbar_w - int(4 * ui_scale)
        
        scrollable_start = self.button_clear.rect.bottom + int(10 * ui_scale)
        scrollable_height = self.height - scrollable_start
        
        if self.panel_content_height <= scrollable_height:
            return None
        
        thumb_height = max(int(30 * ui_scale), int(scrollable_height * scrollable_height / self.panel_content_height))
        scroll_ratio = self.panel_scroll_offset / max(1, self.panel_content_height - scrollable_height)
        thumb_y = scrollable_start + int(scroll_ratio * (scrollable_height - thumb_height))
        
        return pygame.Rect(scrollbar_x, thumb_y, scrollbar_w, thumb_height)
    def _update_scale_from_mouse(self, mouse_x):
        """Update scale preview based on mouse x position on slider"""
        if not hasattr(self, '_slider_rect'):
            return
        
        # Calculate new scale (0.5x to 3.0x)
        normalized = (mouse_x - self._slider_rect.x) / self._slider_rect.w
        normalized = max(0.0, min(1.0, normalized))
        new_scale = 0.5 + normalized * (3.0 - 0.5)
        
        # Store preview scale (don't apply until mouse up)
        self.scale_slider_preview = new_scale
    
    def _apply_scale_change(self):
        """Apply the previewed scale change"""
        if self.scale_slider_preview is None:
            return
        
        # Update scale and rebuild UI
        self.renderer.dimensions.scale = self.scale_slider_preview
        self.scale_slider_preview = None
        self._update_fonts()
        
        # Update canvas width with new scale
        ui_scale = self._get_ui_scale()
        self.canvas_width = self.width - int(PANEL_WIDTH * ui_scale)
        self.renderer.canvas_width = self.canvas_width
        self._build_ui()
    
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.VIDEORESIZE:
                self.width, self.height = event.w, event.h
                ui_scale = self._get_ui_scale()
                self.canvas_width  = self.width - int(PANEL_WIDTH * ui_scale)
                self.renderer.canvas_width = self.canvas_width
                self._build_ui()

            elif event.type == pygame.KEYDOWN:
                if not self._on_key(event): return False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.pos[0] >= self.canvas_width: self._on_panel_click(event)
                else:                              self._on_canvas_press(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    self.drawing = False
                    self.renderer.stop_pan()
                    self.scrollbar_dragging = False
                    # Apply scale change if slider was being dragged
                    if self.scale_slider_dragging:
                        self._apply_scale_change()
                    self.scale_slider_dragging = False
                    self._last_paint_pos = None
                elif event.button == 3:
                    self.erasing = False
                    self._last_paint_pos = None
                elif event.button == 2:
                    self.renderer.stop_pan()

            elif event.type == pygame.MOUSEMOTION:
                if self.scrollbar_dragging:
                    # Calculate scroll based on drag
                    ui_scale = self._get_ui_scale()
                    scrollable_start = self.button_clear.rect.bottom + int(10 * ui_scale)
                    scrollable_height = self.height - scrollable_start
                    
                    dy = event.pos[1] - self.scrollbar_drag_start_y
                    thumb_height = max(int(30 * ui_scale), int(scrollable_height * scrollable_height / self.panel_content_height))
                    scroll_range = scrollable_height - thumb_height
                    content_range = self.panel_content_height - scrollable_height
                    
                    if scroll_range > 0:
                        scroll_delta = dy * content_range / scroll_range
                        self.panel_scroll_offset = self.scrollbar_drag_start_scroll + scroll_delta
                
                elif self.scale_slider_dragging:
                    self._update_scale_from_mouse(event.pos[0])
                elif self.renderer.panning:
                    self.renderer.update_pan(event.pos)
                elif event.pos[0] < self.canvas_width:
                    if   self.drawing: self.paint(event.pos[0], event.pos[1])
                    elif self.erasing: self.paint(event.pos[0], event.pos[1], erase=True)

            elif event.type == pygame.MOUSEWHEEL:
                mouse_x, mouse_y = pygame.mouse.get_pos()
                if mouse_x < self.canvas_width:
                    # Zoom canvas
                    self.renderer.zoom(event.y, mouse_x, mouse_y)
                else:
                    # Scroll panel
                    ui_scale = self._get_ui_scale()
                    scroll_amount = int(30 * ui_scale)
                    self.panel_scroll_offset -= event.y * scroll_amount

        return True

    def _on_key(self, event):
        ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
        key    = event.key
        if key == pygame.K_z and ctrl:
            self.undo()
        elif key == pygame.K_y and ctrl:
            self.redo()
        elif key == pygame.K_s:
            if ctrl or self.current_file is None: self.save(force_dialog=True)
            else:                                  self.save(self.current_file)
        elif key == pygame.K_l:   self.load()
        elif key == pygame.K_TAB:
            if   self.mode == MODE_DRAW: self.mode = MODE_LANE
            elif self.mode == MODE_LANE: self.mode = MODE_GOAL
            else:                        self.mode = MODE_DRAW
        elif key == pygame.K_LEFTBRACKET:  self.brush_radius = max(0, self.brush_radius - 1)
        elif key == pygame.K_RIGHTBRACKET: self.brush_radius = min(500, self.brush_radius + 1)
        elif key == pygame.K_r:   self.renderer.reset_view()
        elif key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self._push_history()
            self.renderer.obstacles.clear()
            self.renderer.lane_lines.clear()
            self.goals.clear()
            self._status("Cleared all obstacles, lane lines, and goals.")
        elif key == pygame.K_ESCAPE: return False
        return True

    def _on_panel_click(self, event):
        # Check scrollbar first
        thumb_rect = self._get_scrollbar_thumb_rect()
        if thumb_rect and thumb_rect.collidepoint(event.pos):
            if event.button == 1:
                self.scrollbar_dragging = True
                self.scrollbar_drag_start_y = event.pos[1]
                self.scrollbar_drag_start_scroll = self.panel_scroll_offset
            return
        
        # Check slider
        if hasattr(self, '_slider_rect') and self._slider_rect.collidepoint(event.pos):
            if event.button == 1:
                self.scale_slider_dragging = True
                self._update_scale_from_mouse(event.pos[0])
            return
        
        # Then check buttons
        if   self.button_draw.hit(event):   self.mode = MODE_DRAW
        elif self.button_lane.hit(event):   self.mode = MODE_LANE
        elif self.button_goal.hit(event):   self.mode = MODE_GOAL
        elif self.button_save.hit(event):
            self.save(self.current_file if self.current_file else None)
        elif self.button_saveas.hit(event): self.save(force_dialog=True)
        elif self.button_load.hit(event):   self.load()
        elif self.button_undo.hit(event):   self.undo()
        elif self.button_redo.hit(event):   self.redo()
        elif self.button_clear.hit(event):
            self._push_history()
            self.renderer.obstacles.clear()
            self.renderer.lane_lines.clear()
            self.goals.clear()
            self._status("Cleared all obstacles, lane lines, and goals.")

    def _on_canvas_press(self, event):
        mouse_x, mouse_y = event.pos
        alt_held = bool(pygame.key.get_mods() & pygame.KMOD_ALT)
        if event.button == 2 or (event.button == 1 and alt_held):
            self.renderer.start_pan(event.pos)
        elif self.mode in (MODE_DRAW, MODE_LANE):
            if   event.button == 1:
                self._push_history()
                self._last_paint_pos = None
                self.drawing = True; self.paint(mouse_x, mouse_y)
            elif event.button == 3:
                self._push_history()
                self._last_paint_pos = None
                self.erasing = True; self.paint(mouse_x, mouse_y, erase=True)
        elif self.mode == MODE_GOAL:
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            if event.button == 1:
                self._push_history()
                self.place_goal(mouse_x, mouse_y, no_mans_land=shift)
            elif event.button == 3:
                self._push_history()
                self.remove_nearest_goal(mouse_x, mouse_y)

    def run(self):
        while True:
            self.clock.tick(60)
            if not self.handle_events(): break
            self.draw()
        pygame.quit(); sys.exit(0)


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="5 cm/cell grid map editor")
    parser.add_argument("path", nargs="?", help="Course folder (or map.json) to open on startup")
    args = parser.parse_args()
    editor = MapEditor()
    if args.path and (os.path.isdir(args.path) or os.path.isfile(args.path)):
        editor.load(args.path)
    editor.run()

if __name__ == "__main__":
    main()
