#!/usr/bin/env python3
"""
Shared base class for map rendering with zoom/pan functionality.
Used by both map_editor.py and map_viewer.py to ensure consistency.
"""

import math
import pygame


# ── Palette ───────────────────────────────────────────────────────────────────
BACKGROUND_COLOR = (248, 248, 252)
GRID_MINOR     = (215, 215, 230)
GRID_MAJOR     = (165, 165, 190)
GRID_SUPER     = (120, 120, 155)
AXIS_COLOR     = (120, 120, 155)
OBSTACLE_COLOR   = (42, 45, 68)
LANE_LINE_COLOR  = (210, 170, 35)
OBSTACLE_SHORT_COLOR = (165, 170, 200)  # Obstacles at MIN_OBSTACLE_HEIGHT_M
OBSTACLE_TALL_COLOR  = (12, 12, 22)     # Obstacles at or above OBSTACLE_TALL_HEIGHT_M


# ── Constants ──────────────────────────────────────────────────────────────────
CELL_RESOLUTION       = 0.05  # Each cell is 5cm
MIN_PPM      = 0.5
MAX_PPM      = 8000.0
DEFAULT_PPM  = 200.0
MAJOR_EVERY  = 10
SUPER_EVERY  = 100

# Obstacle heights (meters). The default matches the pointcloud simulator's fixed extrusion height and is
# used for maps saved before per-cell heights existed.
DEFAULT_OBSTACLE_HEIGHT_M = 0.6096
MIN_OBSTACLE_HEIGHT_M     = 0.05
MAX_OBSTACLE_HEIGHT_M     = 5.0
OBSTACLE_TALL_HEIGHT_M    = 2.0


def _lerp_color(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def height_color(height_m):
    """
    Map an obstacle height to a fill color: lighter is shorter, darker is taller.
    The default height maps exactly to OBSTACLE_COLOR so old maps look unchanged.
    """
    if height_m <= DEFAULT_OBSTACLE_HEIGHT_M:
        t = (height_m - MIN_OBSTACLE_HEIGHT_M) / (DEFAULT_OBSTACLE_HEIGHT_M - MIN_OBSTACLE_HEIGHT_M)
        return _lerp_color(OBSTACLE_SHORT_COLOR, OBSTACLE_COLOR, max(0.0, min(1.0, t)))
    t = (height_m - DEFAULT_OBSTACLE_HEIGHT_M) / (OBSTACLE_TALL_HEIGHT_M - DEFAULT_OBSTACLE_HEIGHT_M)
    return _lerp_color(OBSTACLE_COLOR, OBSTACLE_TALL_COLOR, max(0.0, min(1.0, t)))


class ScaledDimensions:
    """Helper class to compute scaled dimensions based on DPI/scale factor"""
    
    def __init__(self, scale_factor=1.0):
        self._scale = scale_factor
    
    @property
    def scale(self):
        """Current scale factor"""
        return self._scale
    
    @scale.setter
    def scale(self, value):
        """Update scale factor"""
        self._scale = max(0.5, min(3.0, value))  # Clamp between 0.5x and 3.0x
    
    @property
    def min_cell_px(self):
        """Minimum cell size in pixels before LOD merging"""
        return max(2, int(4 * self._scale))
    
    @property
    def grid_line_width(self):
        """Width of grid lines"""
        return max(1, int(1 * self._scale))
    
    @property
    def axis_line_width(self):
        """Width of axis lines"""
        return max(1, int(2 * self._scale))
    
    @property
    def robot_outline_width(self):
        """Width of robot outline"""
        return max(1, int(2 * self._scale))
    
    @property
    def robot_direction_width(self):
        """Width of robot direction indicator"""
        return max(2, int(3 * self._scale))
    
    @property
    def robot_direction_circle_radius(self):
        """Radius of robot direction indicator circle"""
        return max(3, int(5 * self._scale))
    
    @property
    def occupancy_grid_outline_width(self):
        """Width of occupancy grid outline"""
        return max(1, int(2 * self._scale))
    
    @property
    def info_padding_x(self):
        """Horizontal padding for info overlay"""
        return max(5, int(10 * self._scale))
    
    @property
    def info_padding_y(self):
        """Vertical padding for info overlay"""
        return max(2, int(4 * self._scale))
    
    @property
    def info_margin(self):
        """Margin around info overlay"""
        return max(3, int(5 * self._scale))
    
    @property
    def info_line_spacing(self):
        """Spacing between info lines"""
        return max(1, int(2 * self._scale))
    
    @property
    def font_size(self):
        """Font size for info overlay"""
        return max(10, int(13 * self._scale))


class MapRendererBase:
    """
    Base class for map rendering with camera controls.
    Handles coordinate transformations, zoom, pan, and grid/obstacle rendering.
    """
    
    def __init__(self, screen, initial_ppm=DEFAULT_PPM, scale_factor=1.0):
        """
        Initialize the map renderer.
        
        Args:
            screen: pygame Surface to render to
            initial_ppm: Initial pixels per meter zoom level
            scale_factor: DPI/display scale factor for sizing elements
        """
        self.screen = screen
        
        # Scaled dimensions based on DPI
        self.dimensions = ScaledDimensions(scale_factor)
        
        # Camera state
        self.camera_x = 0.0  # Camera position in world coordinates (meters)
        self.camera_y = 0.0
        self.ppm = initial_ppm  # Pixels per meter (zoom level)
        
        # Panning state
        self.panning = False
        self.pan_start = (0, 0)
        self.pan_cam_orig = (0.0, 0.0)
        
        # Map layer state
        self.obstacles: dict[tuple[int, int], float] = {}  # cell -> height (m)
        self.lane_lines: set[tuple[int, int]] = set()
    
    def _lod(self):
        """
        Calculate level-of-detail merging factor.
        Returns (level, block_size) where block_size is the number of cells to merge.
        """
        pixels_per_cell = self.ppm * CELL_RESOLUTION
        min_cell_px = self.dimensions.min_cell_px
        
        if pixels_per_cell >= min_cell_px:
            return 0, 1
        level = 0
        block = 1
        while pixels_per_cell < min_cell_px and block < 2048:
            block *= 2
            level += 1
            pixels_per_cell = self.ppm * CELL_RESOLUTION * block
        return level, block
    
    def world_to_screen(self, world_x, world_y):
        """
        Convert world coordinates (meters) to screen pixels.
        Note: Screen Y increases downward, so we negate world Y.
        
        Args:
            world_x, world_y: World coordinates in meters
            
        Returns:
            (screen_x, screen_y): Screen coordinates in pixels
        """
        screen_width, screen_height = self.screen.get_size()
        screen_x = (world_x - self.camera_x) * self.ppm + screen_width / 2
        screen_y = -(world_y - self.camera_y) * self.ppm + screen_height / 2  # Negate Y for screen coords
        return screen_x, screen_y
    
    def screen_to_world(self, screen_x, screen_y):
        """
        Convert screen pixels to world coordinates (meters).
        Note: Screen Y increases downward, so we negate when converting to world.
        
        Args:
            screen_x, screen_y: Screen coordinates in pixels
            
        Returns:
            (world_x, world_y): World coordinates in meters
        """
        screen_width, screen_height = self.screen.get_size()
        world_x = (screen_x - screen_width / 2) / self.ppm + self.camera_x
        world_y = -(screen_y - screen_height / 2) / self.ppm + self.camera_y  # Negate Y for world coords
        return world_x, world_y
    
    def zoom(self, delta, mouse_x, mouse_y):
        """
        Zoom in/out around mouse position.
        
        Args:
            delta: Scroll direction (positive = zoom in, negative = zoom out)
            mx, my: Mouse position in screen coordinates
        """
        # Store world position under mouse before zoom
        world_x, world_y = self.screen_to_world(mouse_x, mouse_y)
        
        # Apply zoom
        old_ppm = self.ppm
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self.ppm = max(MIN_PPM, min(MAX_PPM, self.ppm * factor))
        
        # Adjust camera so world position stays under mouse
        if self.ppm != old_ppm:
            # After zoom, where would that world point appear on screen?
            sx_new, sy_new = self.world_to_screen(world_x, world_y)
            
            # Calculate how much it shifted
            dx_screen = sx_new - mouse_x
            dy_screen = sy_new - mouse_y
            
            # Adjust camera to compensate
            self.camera_x += dx_screen / self.ppm
            self.camera_y += dy_screen / self.ppm
    
    def reset_view(self):
        """Reset camera to origin with default zoom"""
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.ppm = DEFAULT_PPM
    
    def start_pan(self, mouse_pos):
        """
        Begin panning operation.
        
        Args:
            mouse_pos: (x, y) mouse position when panning started
        """
        self.panning = True
        self.pan_start = mouse_pos
        self.pan_cam_orig = (self.camera_x, self.camera_y)
    
    def update_pan(self, mouse_pos):
        """
        Update camera position during pan.
        
        Args:
            mouse_pos: Current (x, y) mouse position
        """
        if self.panning:
            mouse_x, mouse_y = mouse_pos
            dx = (mouse_x - self.pan_start[0]) / self.ppm
            dy = (mouse_y - self.pan_start[1]) / self.ppm
            self.camera_x = self.pan_cam_orig[0] - dx
            self.camera_y = self.pan_cam_orig[1] + dy  # + because screen Y is inverted

    
    def stop_pan(self):
        """End panning operation"""
        self.panning = False
    
    def draw_grid(self):
        """Draw coordinate grid with axes"""
        screen_width, screen_height = self.screen.get_size()
        _, block = self._lod()
        
        # Calculate grid range - get all four corners and find true min/max
        tl_x, tl_y = self.screen_to_world(0, 0)
        tr_x, tr_y = self.screen_to_world(screen_width, 0)
        bl_x, bl_y = self.screen_to_world(0, screen_height)
        br_x, br_y = self.screen_to_world(screen_width, screen_height)
        
        x_min = min(tl_x, tr_x, bl_x, br_x)
        x_max = max(tl_x, tr_x, bl_x, br_x)
        y_min = min(tl_y, tr_y, bl_y, br_y)
        y_max = max(tl_y, tr_y, bl_y, br_y)
        
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
            pygame.draw.line(self.screen, color, (0, screen_y), (screen_width, screen_y), grid_line_width)
            y += grid_size
        
        # Draw axes
        x0, _ = self.world_to_screen(0, 0)
        _, y0 = self.world_to_screen(0, 0)
        axis_line_width = self.dimensions.axis_line_width
        pygame.draw.line(self.screen, AXIS_COLOR, (x0, 0), (x0, screen_height), axis_line_width)
        pygame.draw.line(self.screen, AXIS_COLOR, (0, y0), (screen_width, y0), axis_line_width)
    
    def _draw_cells(self, cells, color: tuple, heights: dict | None = None) -> None:
        """
        Draw a set of grid cells with LOD merging.
        If `heights` is given, each merged block is colored by the tallest cell in it.
        """
        _, block = self._lod()
        merged_cells = {}
        for cell_x, cell_y in cells:
            block_x = (cell_x // block) * block
            block_y = (cell_y // block) * block
            height = heights[(cell_x, cell_y)] if heights is not None else 0.0
            if merged_cells.get((block_x, block_y), -1.0) < height:
                merged_cells[(block_x, block_y)] = height

        cell_screen = CELL_RESOLUTION * block * self.ppm
        for (block_x, block_y), height in merged_cells.items():
            screen_x, screen_y = self.world_to_screen(block_x * CELL_RESOLUTION, block_y * CELL_RESOLUTION)
            fill = height_color(height) if heights is not None else color
            pygame.draw.rect(self.screen, fill, pygame.Rect(screen_x, screen_y, cell_screen, cell_screen))

    def draw_obstacles(self):
        """Draw obstacle cells with LOD merging, shaded by height."""
        self._draw_cells(self.obstacles, OBSTACLE_COLOR, self.obstacles)

    def draw_lane_lines(self):
        """Draw lane-line cells with LOD merging (distinct color, no shadow)."""
        self._draw_cells(self.lane_lines, LANE_LINE_COLOR)
