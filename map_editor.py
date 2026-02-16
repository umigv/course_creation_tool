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
  RMB click       -> remove nearest goal      (Goal mode)
  MMB drag        -> pan camera
  Alt+LMB drag    -> pan camera (laptop-friendly)
  Scroll wheel    -> zoom in / out
  Tab             -> toggle Draw / Goal mode
  [ / ]           -> shrink / grow brush
  Ctrl+Z          -> undo
  Ctrl+Y          -> redo
  S               -> save  (quick-save if file known, else prompts)
  Ctrl+S          -> save-as (always prompts)
  L               -> load (prompts for filename)
  R               -> reset view to origin
  Delete          -> clear all
"""

import math, json, os, sys
import pygame
import argparse
from map_renderer_base import MapRendererBase, BG_COLOR, CELL_M, DEFAULT_PPM
from dpi_utils import setup_pygame_dpi_awareness, get_system_scale_factor


# ── Additional Palette for Editor ────────────────────────────────────────────
GOAL_FILL      = (240,  65,  65)
GOAL_RING      = (170,   0,   0)
PANEL_BG       = ( 32,  36,  48)
PANEL_FG       = (218, 224, 238)
PANEL_DIM      = (110, 118, 140)
PANEL_SEP      = ( 55,  62,  78)
BTN_ACTIVE     = ( 72, 136, 255)
BTN_IDLE       = ( 58,  64,  82)
BTN_HOVER      = ( 80,  88, 110)
BRUSH_DRAW     = ( 72, 108, 230, 100)
BRUSH_ERASE    = (230,  72,  72, 100)
SCALE_COL      = ( 55,  58,  80)

DIALOG_BG      = ( 22,  26,  38)
DIALOG_BORDER  = ( 72, 136, 255)
DIALOG_INPUT   = ( 38,  44,  60)
DIALOG_CURSOR  = (160, 200, 255)
DIALOG_OK      = ( 60, 160,  80)
DIALOG_CANCEL  = (160,  60,  60)
DIALOG_ERR     = (220,  80,  80)

# ── Constants ──────────────────────────────────────────────────────────────────
PANEL_W      = 240
MODE_DRAW    = "draw"
MODE_GOAL    = "goal"


# ─────────────────────────────────────────────────────────────────────────────
# In-pygame file dialog
# ─────────────────────────────────────────────────────────────────────────────
class FileDialog:
    """
    Blocking modal text-entry dialog drawn directly onto the pygame surface.
    Call FileDialog.ask(...) which spins its own mini event loop and returns
    a string (the typed path) or None if cancelled.
    """

    @staticmethod
    def ask(screen, font_m, font_s, title="Enter filename",
            initial="", error=""):
        """
        Runs a modal input loop.  Returns the entered string or None.
        """
        clock   = pygame.time.Clock()
        text    = initial
        cursor_on    = True
        cursor_timer = 0
        err_msg = error

        SW, SH = screen.get_size()
        W, H   = min(620, SW - 40), 200
        x      = (SW - W) // 2
        y      = (SH - H) // 2

        # Button rects (local coords inside dialog)
        ok_rect     = pygame.Rect(W - 190, H - 52, 82, 34)
        cancel_rect = pygame.Rect(W -  98, H - 52, 82, 34)
        input_rect  = pygame.Rect(16, 80, W - 32, 36)

        while True:
            clock.tick(60)
            cursor_timer += 1
            if cursor_timer >= 30:
                cursor_on    = not cursor_on
                cursor_timer = 0

            # ── Draw overlay ────────────────────────────────────────────────
            overlay = pygame.Surface((SW, SH), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            screen.blit(overlay, (0, 0))

            # Dialog box
            box = pygame.Rect(x, y, W, H)
            pygame.draw.rect(screen, DIALOG_BG, box, border_radius=12)
            pygame.draw.rect(screen, DIALOG_BORDER, box, 2, border_radius=12)

            # Title
            t = font_m.render(title, True, PANEL_FG)
            screen.blit(t, (x + 16, y + 16))

            # Hint
            h = font_s.render("Press Enter to confirm, Esc to cancel", True, PANEL_DIM)
            screen.blit(h, (x + 16, y + 46))

            # Input box
            ib = input_rect.move(x, y)
            pygame.draw.rect(screen, DIALOG_INPUT, ib, border_radius=6)
            pygame.draw.rect(screen, DIALOG_BORDER, ib, 1, border_radius=6)

            # Clip text to fit box width
            max_w   = ib.width - 20
            display = text
            while font_s.size(display)[0] > max_w and display:
                display = display[1:]

            txt_surf = font_s.render(display, True, PANEL_FG)
            screen.blit(txt_surf, (ib.x + 8, ib.y + 10))

            # Cursor
            if cursor_on:
                cx = ib.x + 8 + font_s.size(display)[0]
                pygame.draw.line(screen, DIALOG_CURSOR,
                                 (cx, ib.y + 8), (cx, ib.y + 26), 2)

            # Error message
            if err_msg:
                e = font_s.render(err_msg, True, DIALOG_ERR)
                screen.blit(e, (x + 16, y + 122))

            # Buttons
            mx, my = pygame.mouse.get_pos()

            def btn(rect_local, label, base_col):
                r = rect_local.move(x, y)
                hover = r.collidepoint(mx, my)
                col   = tuple(min(255, c + 30) for c in base_col) if hover else base_col
                pygame.draw.rect(screen, col, r, border_radius=7)
                s = font_s.render(label, True, (240, 240, 240))
                screen.blit(s, s.get_rect(center=r.center))
                return r

            ok_r     = btn(ok_rect,     "OK",     DIALOG_OK)
            cancel_r = btn(cancel_rect, "Cancel", DIALOG_CANCEL)

            pygame.display.flip()

            # ── Events ──────────────────────────────────────────────────────
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit(0)

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    elif event.key == pygame.K_RETURN:
                        result = text.strip()
                        return result if result else None
                    elif event.key == pygame.K_BACKSPACE:
                        text = text[:-1]
                        err_msg = ""
                    else:
                        ch = event.unicode
                        if ch and ch.isprintable():
                            text   += ch
                            err_msg = ""

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if ok_r.collidepoint(event.pos):
                        result = text.strip()
                        return result if result else None
                    elif cancel_r.collidepoint(event.pos):
                        return None


# ─────────────────────────────────────────────────────────────────────────────
# Button widget
# ─────────────────────────────────────────────────────────────────────────────
class Button:
    def __init__(self, rect, label, active=False, color_active=None):
        self.rect        = pygame.Rect(rect)
        self.label       = label
        self.active      = active
        self.hover       = False
        self._col_active = color_active or BTN_ACTIVE

    def draw(self, surf, font):
        col = self._col_active if self.active else (BTN_HOVER if self.hover else BTN_IDLE)
        pygame.draw.rect(surf, col, self.rect, border_radius=7)
        txt = font.render(self.label, True, PANEL_FG)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def update(self, mpos): self.hover = self.rect.collidepoint(mpos)
    def hit(self, ev):
        return (ev.type == pygame.MOUSEBUTTONDOWN
                and ev.button == 1
                and self.rect.collidepoint(ev.pos))


# ─────────────────────────────────────────────────────────────────────────────
# Renderer subclass for editor with panel offset
# ─────────────────────────────────────────────────────────────────────────────
class EditorRenderer(MapRendererBase):
    """
    Extends MapRendererBase to handle the right-side panel offset.
    The canvas is (W - PANEL_W) wide, and coordinates are adjusted accordingly.
    """
    
    def __init__(self, screen, canvas_width, initial_ppm=DEFAULT_PPM, scale_factor=1.0):
        super().__init__(screen, initial_ppm, scale_factor)
        self.canvas_W = canvas_width
    
    def world_to_screen(self, wx, wy):
        """Override to use canvas_W instead of full screen width"""
        W, H = self.screen.get_size()
        sx = (wx - self.cam_x) * self.ppm + self.canvas_W / 2
        sy = -(wy - self.cam_y) * self.ppm + H / 2  # Negate Y for screen coords
        return sx, sy
    
    def screen_to_world(self, sx, sy):
        """Override to use canvas_W instead of full screen width"""
        W, H = self.screen.get_size()
        wx = (sx - self.canvas_W / 2) / self.ppm + self.cam_x
        wy = -(sy - H / 2) / self.ppm + self.cam_y  # Negate Y for world coords
        return wx, wy
    
    def draw_grid(self):
        """Override to clip grid to canvas area"""
        W, H = self.screen.get_size()
        _, block = self._lod()
        
        # Calculate grid range - only for canvas area
        tl_x, tl_y = self.screen_to_world(0, 0)
        tr_x, tr_y = self.screen_to_world(self.canvas_W, 0)
        bl_x, bl_y = self.screen_to_world(0, H)
        br_x, br_y = self.screen_to_world(self.canvas_W, H)
        
        x_min = min(tl_x, tr_x, bl_x, br_x)
        x_max = max(tl_x, tr_x, bl_x, br_x)
        y_min = min(tl_y, tr_y, bl_y, br_y)
        y_max = max(tl_y, tr_y, bl_y, br_y)
        
        from map_renderer_base import GRID_MINOR, GRID_MAJOR, GRID_SUPER, AXIS_COLOR, SUPER_EVERY, MAJOR_EVERY
        
        grid_size = CELL_M * block
        start_x = math.floor(x_min / grid_size) * grid_size
        start_y = math.floor(y_min / grid_size) * grid_size
        
        grid_line_width = self.dims.grid_line_width
        
        # Vertical lines
        x = start_x
        while x <= x_max:
            sx, _ = self.world_to_screen(x, 0)
            cell_idx = int(round(x / CELL_M))
            if cell_idx % (SUPER_EVERY * block) == 0:
                color = GRID_SUPER
            elif cell_idx % (MAJOR_EVERY * block) == 0:
                color = GRID_MAJOR
            else:
                color = GRID_MINOR
            if 0 <= sx <= self.canvas_W:
                pygame.draw.line(self.screen, color, (sx, 0), (sx, H), grid_line_width)
            x += grid_size
        
        # Horizontal lines
        y = start_y
        while y <= y_max:
            _, sy = self.world_to_screen(0, y)
            cell_idx = int(round(y / CELL_M))
            if cell_idx % (SUPER_EVERY * block) == 0:
                color = GRID_SUPER
            elif cell_idx % (MAJOR_EVERY * block) == 0:
                color = GRID_MAJOR
            else:
                color = GRID_MINOR
            pygame.draw.line(self.screen, color, (0, sy), (self.canvas_W, sy), grid_line_width)
            y += grid_size
        
        # Draw axes (clipped to canvas)
        x0, _ = self.world_to_screen(0, 0)
        _, y0 = self.world_to_screen(0, 0)
        axis_line_width = self.dims.axis_line_width
        if 0 <= x0 <= self.canvas_W:
            pygame.draw.line(self.screen, AXIS_COLOR, (x0, 0), (x0, H), axis_line_width)
        if 0 <= y0 <= H:
            pygame.draw.line(self.screen, AXIS_COLOR, (0, y0), (self.canvas_W, y0), axis_line_width)


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
        self.W, self.H = int(width * scale_factor), int(height * scale_factor)
        self.canvas_W  = self.W - int(PANEL_W * scale_factor)
        self.screen    = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        pygame.display.set_caption("Map Editor  |  5 cm / cell")

        # Scale fonts based on DPI
        font_size_s = max(11, int(13 * scale_factor))
        font_size_m = max(13, int(15 * scale_factor))
        font_size_l = max(15, int(18 * scale_factor))
        
        self.font_s = pygame.font.SysFont("monospace", font_size_s)
        self.font_m = pygame.font.SysFont("monospace", font_size_m, bold=True)
        self.font_l = pygame.font.SysFont("monospace", font_size_l, bold=True)
        self.clock  = pygame.time.Clock()

        # Initialize renderer
        self.renderer = EditorRenderer(self.screen, self.canvas_W, DEFAULT_PPM, scale_factor)

        self.goals: list     = []      # world metres (x, y)

        self.mode          = MODE_DRAW
        self.brush_cells   = 1
        self.drawing       = False
        self.erasing       = False
        self._last_paint_pos: tuple | None = None   # for stroke interpolation
        self.current_file  = None
        self.status_msg    = ""
        self.status_timer  = 0

        # Undo / redo stacks — each entry is (frozenset_obstacles, tuple_goals)
        self._undo_stack: list = []
        self._redo_stack: list = []
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
        return self.renderer.dims.scale
    
    def _get_ui_scale(self):
        """Get current UI scale factor for layout calculations"""
        return self.renderer.dims.scale

    # ── Coordinates ────────────────────────────────────────────────────────────
    def _update_fonts(self):
        """Recreate fonts with current scale"""
        font_size_s = max(11, int(13 * self.renderer.dims.scale))
        font_size_m = max(13, int(15 * self.renderer.dims.scale))
        font_size_l = max(15, int(18 * self.renderer.dims.scale))
        
        self.font_s = pygame.font.SysFont("monospace", font_size_s)
        self.font_m = pygame.font.SysFont("monospace", font_size_m, bold=True)
        self.font_l = pygame.font.SysFont("monospace", font_size_l, bold=True)
    
    def world_to_base_cell(self, wx, wy):
        """Convert world coordinates to cell indices (row, col)"""
        return (int(math.floor(wy / CELL_M)),
                int(math.floor(wx / CELL_M)))

    # ── Edit operations ────────────────────────────────────────────────────────
    def _stamp(self, sx, sy, erase=False):
        """Stamp the brush once at screen position (sx, sy)."""
        wx, wy = self.renderer.screen_to_world(sx, sy)
        cr, cc = self.world_to_base_cell(wx, wy)
        r = self.brush_cells
        for dr in range(-r, r + 1):
            for dc in range(-r, r + 1):
                if dr * dr + dc * dc <= r * r:
                    key = (cr + dr, cc + dc)
                    if erase:
                        self.renderer.obstacles.discard(key)
                    else:
                        self.renderer.obstacles.add(key)

    def paint(self, sx, sy, erase=False):
        """Paint from the last position to (sx, sy), interpolating to fill gaps."""
        if self._last_paint_pos is None:
            self._stamp(sx, sy, erase)
        else:
            x0, y0 = self._last_paint_pos
            dx, dy = sx - x0, sy - y0
            dist = math.hypot(dx, dy)
            # Step at most half a cell-width so no cell is ever skipped
            step = max(1.0, CELL_M * self.renderer.ppm * 0.5)
            steps = max(1, int(dist / step))
            for i in range(steps + 1):
                t = i / steps
                self._stamp(x0 + dx * t, y0 + dy * t, erase)
        self._last_paint_pos = (sx, sy)

    def place_goal(self, sx, sy):
        wx, wy = self.renderer.screen_to_world(sx, sy)
        self.goals.append((wx, wy))

    def remove_nearest_goal(self, sx, sy):
        if not self.goals: return
        wx, wy    = self.renderer.screen_to_world(sx, sy)
        threshold = 25 / self.renderer.ppm
        idx = min(range(len(self.goals)),
                  key=lambda i: (self.goals[i][0]-wx)**2 + (self.goals[i][1]-wy)**2)
        if math.hypot(self.goals[idx][0]-wx, self.goals[idx][1]-wy) <= threshold:
            self.goals.pop(idx)

    # ── File I/O ────────────────────────────────────────────────────────────────
    def _ensure_json_ext(self, path):
        if path and not path.lower().endswith(".json"):
            path += ".json"
        return path

    def save(self, path=None, force_dialog=False):
        if path is None or force_dialog:
            initial = os.path.basename(path or self.current_file or "map.json")
            path = FileDialog.ask(
                self.screen, self.font_m, self.font_s,
                title="Save map — enter filename",
                initial=initial)
            if path is None:
                return
            path = self._ensure_json_ext(path)

        try:
            data = {
                "cell_m":    CELL_M,
                "obstacles": [list(o) for o in self.renderer.obstacles],
                "goals":     [list(g) for g in self.goals],
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self.current_file = path
            self._status(f"Saved -> {os.path.basename(path)}")
        except OSError as e:
            # Show error inside the dialog and let user retry with corrected path
            new_path = FileDialog.ask(
                self.screen, self.font_m, self.font_s,
                title="Save map — enter filename",
                initial=path,
                error=f"Error: {e}")
            if new_path:
                self.save(self._ensure_json_ext(new_path))

    def load(self, path=None):
        if path is None:
            path = FileDialog.ask(
                self.screen, self.font_m, self.font_s,
                title="Load map — enter filename",
                initial=os.path.basename(self.current_file or "map.json"))
            if path is None:
                return
            path = self._ensure_json_ext(path)

        if not os.path.isfile(path):
            new_path = FileDialog.ask(
                self.screen, self.font_m, self.font_s,
                title="Load map — enter filename",
                initial=path,
                error=f"File not found: {path}")
            if new_path:
                self.load(self._ensure_json_ext(new_path))
            return

        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            FileDialog.ask(
                self.screen, self.font_m, self.font_s,
                title="Load failed — press Esc to close",
                initial="",
                error=str(e))
            return

        saved_cm = float(data.get("cell_m", CELL_M))
        scale    = max(1, round(saved_cm / CELL_M))

        self.renderer.obstacles = set()
        for o in data.get("obstacles", []):
            r0, c0 = int(o[0]), int(o[1])
            for dr in range(scale):
                for dc in range(scale):
                    self.renderer.obstacles.add((r0*scale + dr, c0*scale + dc))

        self.goals        = [tuple(g) for g in data.get("goals", [])]
        self.current_file = path
        self._status(f"Loaded <- {os.path.basename(path)}")

    def _status(self, msg, secs=3.0):
        self.status_msg   = msg
        self.status_timer = int(secs * 60)

    # ── Undo / redo ─────────────────────────────────────────────────────────────
    def _push_history(self):
        """Save current state onto the undo stack and clear the redo stack."""
        entry = (frozenset(self.renderer.obstacles), tuple(self.goals))
        if self._undo_stack and self._undo_stack[-1] == entry:
            return  # nothing changed — don't create a duplicate entry
        self._undo_stack.append(entry)
        if len(self._undo_stack) > self._MAX_HISTORY:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore(self, entry):
        obs, goals = entry
        self.renderer.obstacles = set(obs)
        self.goals     = list(goals)

    def undo(self):
        if not self._undo_stack:
            self._status("Nothing to undo.", 1.5); return
        current = (frozenset(self.renderer.obstacles), tuple(self.goals))
        self._redo_stack.append(current)
        self._restore(self._undo_stack.pop())
        self._status("Undo", 1.0)

    def redo(self):
        if not self._redo_stack:
            self._status("Nothing to redo.", 1.5); return
        current = (frozenset(self.renderer.obstacles), tuple(self.goals))
        self._undo_stack.append(current)
        self._restore(self._redo_stack.pop())
        self._status("Redo", 1.0)

    # ── Rendering ───────────────────────────────────────────────────────────────
    def draw(self):
        self.screen.fill(BG_COLOR)
        self.renderer.draw_obstacles()
        self._draw_goals()
        self._draw_brush_preview()
        self.renderer.draw_grid()  # Draw grid on top
        self._draw_scale_bar()
        self._draw_coords_lod()
        self._draw_status()
        self._draw_panel()
        pygame.display.flip()

    def _draw_goals(self):
        r_px = max(7, min(26, CELL_M * 1.0 * self.renderer.ppm))
        ri   = int(r_px)
        for gx, gy in self.goals:
            sx, sy = self.renderer.world_to_screen(gx, gy)
            si, sj = int(sx), int(sy)
            if -ri <= si <= self.canvas_W + ri and -ri <= sj <= self.H + ri:
                pygame.draw.circle(self.screen, GOAL_FILL, (si, sj), ri)
                pygame.draw.circle(self.screen, GOAL_RING, (si, sj), ri, 2)
                pygame.draw.line(self.screen, GOAL_RING, (si-ri, sj), (si+ri, sj), 2)
                pygame.draw.line(self.screen, GOAL_RING, (si, sj-ri), (si, sj+ri), 2)

    def _draw_brush_preview(self):
        mx, my = pygame.mouse.get_pos()
        if mx >= self.canvas_W: return
        if self.mode == MODE_DRAW:
            r_px = max(2, int((self.brush_cells + 0.5) * CELL_M * self.renderer.ppm))
            col  = BRUSH_ERASE if self.erasing else BRUSH_DRAW
            surf = pygame.Surface((r_px*2+4, r_px*2+4), pygame.SRCALPHA)
            pygame.draw.circle(surf, col, (r_px+2, r_px+2), r_px)
            self.screen.blit(surf, (mx-r_px-2, my-r_px-2))
            pygame.draw.circle(self.screen,
                               (200,60,60) if self.erasing else (60,80,200),
                               (mx, my), r_px, 1)
        else:
            ri = max(7, min(26, int(CELL_M * self.renderer.ppm)))
            pygame.draw.circle(self.screen, GOAL_FILL, (mx, my), ri, 2)
            pygame.draw.line(self.screen, GOAL_FILL, (mx-ri, my), (mx+ri, my), 1)
            pygame.draw.line(self.screen, GOAL_FILL, (mx, my-ri), (mx, my+ri), 1)

    def _draw_scale_bar(self):
        target_px  = 160
        world_span = target_px / self.renderer.ppm
        magnitude  = 10 ** math.floor(math.log10(max(world_span, 1e-9)))
        nice_vals  = [0.1,0.2,0.5,1,2,5,10,20,50,100,200,500,1000]
        world_len  = magnitude
        for v in nice_vals:
            if v * magnitude >= world_span * 0.4:
                world_len = v * magnitude; break
        bar_px = int(world_len * self.renderer.ppm)
        bx, by = 18, self.H - 38
        pygame.draw.rect(self.screen, SCALE_COL, (bx, by, bar_px, 5))
        pygame.draw.line(self.screen, SCALE_COL, (bx, by-5), (bx, by+10), 2)
        pygame.draw.line(self.screen, SCALE_COL, (bx+bar_px, by-5), (bx+bar_px, by+10), 2)
        if world_len >= 1:   label = f"{world_len:.4g} m"
        elif world_len >= 0.01: label = f"{world_len*100:.4g} cm"
        else:                label = f"{world_len*1000:.4g} mm"
        txt = self.font_s.render(label, True, SCALE_COL)
        self.screen.blit(txt, (bx + bar_px//2 - txt.get_width()//2, by+12))

    def _draw_coords_lod(self):
        level, block = self.renderer._lod()
        mx, my = pygame.mouse.get_pos()
        if mx < self.canvas_W:
            wx, wy = self.renderer.screen_to_world(mx, my)
            cr, cc = self.world_to_base_cell(wx, wy)
            txt = self.font_s.render(
                f"({wx:+.4f}, {wy:+.4f}) m   cell ({cc}, {cr})   LOD {level} ({block}x{block})",
                True, SCALE_COL)
            self.screen.blit(txt, (18, self.H - 60))

    def _draw_status(self):
        if self.status_timer > 0:
            self.status_timer -= 1
            surf = self.font_s.render(self.status_msg, True, (80, 200, 80))
            surf.set_alpha(min(255, self.status_timer * 6))
            self.screen.blit(surf, (18, self.H - 80))

    # ── Panel ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        ui_scale = self._get_ui_scale()
        panel_w = int(PANEL_W * ui_scale)
        px = self.canvas_W + int(10 * ui_scale)
        bw = panel_w - int(20 * ui_scale)
        hw = (bw - int(6 * ui_scale)) // 2  # half-width for side-by-side buttons

        self.btn_draw   = Button((px,  int(48 * ui_scale), bw, int(36 * ui_scale)), "Draw Obstacles", active=(self.mode==MODE_DRAW))
        self.btn_goal   = Button((px,  int(90 * ui_scale), bw, int(36 * ui_scale)), "Place Goals",    active=(self.mode==MODE_GOAL))

        # File operations — start AFTER the info-text block (sep at 196, text 142-192)
        self.btn_save   = Button((px, int(204 * ui_scale), bw, int(32 * ui_scale)), "Save")
        self.btn_saveas = Button((px, int(242 * ui_scale), bw, int(32 * ui_scale)), "Save As...")
        self.btn_load   = Button((px, int(280 * ui_scale), bw, int(32 * ui_scale)), "Load...")

        # Undo / Redo — after sep at 320, "History" micro-label at 322
        self.btn_undo   = Button((px,                             int(338 * ui_scale), hw, int(32 * ui_scale)), "↩  Undo")
        self.btn_redo   = Button((px + hw + int(6 * ui_scale), int(338 * ui_scale), hw, int(32 * ui_scale)), "Redo  ↪")

        # Danger zone — after sep at 378
        self.btn_clear  = Button((px, int(386 * ui_scale), bw, int(32 * ui_scale)), "Clear All",
                                 color_active=(200, 60, 60))

        self.buttons = [self.btn_draw, self.btn_goal,
                        self.btn_save, self.btn_saveas, self.btn_load,
                        self.btn_undo, self.btn_redo,
                        self.btn_clear]

    def _draw_panel(self):
        ui_scale = self._get_ui_scale()
        panel_w = int(PANEL_W * ui_scale)
        mpos = pygame.mouse.get_pos()
        
        # Draw panel background
        pygame.draw.rect(self.screen, PANEL_BG, (self.canvas_W, 0, panel_w, self.H))
        pygame.draw.line(self.screen, PANEL_SEP, (self.canvas_W, 0), (self.canvas_W, self.H), 2)

        # Title (not scrolled)
        t = self.font_l.render("MAP  EDITOR", True, PANEL_FG)
        self.screen.blit(t, (self.canvas_W + panel_w//2 - t.get_width()//2, int(14 * ui_scale)))

        # Buttons (not scrolled)
        self.btn_draw.active = self.mode == MODE_DRAW
        self.btn_goal.active = self.mode == MODE_GOAL
        for btn in self.buttons:
            btn.update(mpos)
            btn.draw(self.screen, self.font_s)

        # Scrollable content starts after last button
        scrollable_start = self.btn_clear.rect.bottom + int(10 * ui_scale)
        scrollable_height = self.H - scrollable_start
        
        # Create virtual surface for scrollable content
        virtual_h = max(4000, self.H * 2)
        virtual_surf = pygame.Surface((panel_w, virtual_h))
        virtual_surf.fill(PANEL_BG)
        
        bx_virtual = int(10 * ui_scale)
        bx_screen = self.canvas_W + int(10 * ui_scale)
        y = 0
        
        # Helper functions drawing to virtual surface
        def sep(spacing=8):
            nonlocal y
            y += int(spacing * ui_scale)
            pygame.draw.line(virtual_surf, PANEL_SEP,
                           (bx_virtual, y), (panel_w - int(10 * ui_scale), y), 1)
            y += int(4 * ui_scale)
        
        def lbl(text, col=PANEL_FG, spacing=0):
            nonlocal y
            y += int(spacing * ui_scale)
            s = self.font_s.render(text, True, col)
            virtual_surf.blit(s, (bx_virtual, y))
            y += s.get_height() + int(2 * ui_scale)

        # Scrollable content starts here
        y = 0
        
        # Mode/brush info
        sep(4)
        lbl(f"Mode  : {'DRAW' if self.mode==MODE_DRAW else 'GOAL'}")
        if self.mode == MODE_DRAW:
            diam_m = (self.brush_cells * 2 + 1) * CELL_M
            lbl(f"Brush : r={self.brush_cells} ({diam_m:.2f} m diam)")
            lbl("  [ / ]  to resize", PANEL_DIM)

        # Stats
        sep(8)
        lbl("-- Stats --", PANEL_DIM, 4)
        level, block = self.renderer._lod()
        lbl(f"LOD   : {level}  ({block}x{block} cells merged)")
        lbl(f"Display cell = {CELL_M*block*100:.4g} cm")
        lbl(f"Obstacles : {len(self.renderer.obstacles):,}")
        lbl(f"Goals     : {len(self.goals)}")
        lbl(f"Zoom      : {self.renderer.ppm:.1f} px/m")
        lbl(f"Base cell : {CELL_M*100:.0f} cm (fixed)")

        sep(8)
        fn = os.path.basename(self.current_file) if self.current_file else "(unsaved)"
        lbl(f"File: {fn}", PANEL_DIM)
        
        # UI Scale Slider
        sep(8)
        display_scale = self.scale_slider_preview if self.scale_slider_preview is not None else self.renderer.dims.scale
        lbl(f"UI Scale: {display_scale:.2f}x", PANEL_DIM)
        
        slider_w = panel_w - int(40 * ui_scale)
        slider_x_virtual = bx_virtual + int(10 * ui_scale)
        slider_y_virtual = y + int(4 * ui_scale)
        track_h = int(4 * ui_scale)
        
        pygame.draw.rect(virtual_surf, (60, 66, 85), 
                        pygame.Rect(slider_x_virtual, slider_y_virtual, slider_w, track_h), 
                        border_radius=2)
        
        scale_range = 3.0 - 0.5
        normalized = (display_scale - 0.5) / scale_range
        thumb_x = slider_x_virtual + int(normalized * slider_w)
        thumb_y = slider_y_virtual + track_h // 2
        thumb_radius = int(7 * ui_scale)
        
        thumb_color = (100, 150, 255) if self.scale_slider_dragging else BTN_ACTIVE
        pygame.draw.circle(virtual_surf, thumb_color, (thumb_x, thumb_y), thumb_radius)
        pygame.draw.circle(virtual_surf, PANEL_FG, (thumb_x, thumb_y), thumb_radius - 2)
        
        # Store slider rect (adjusted for scroll and screen position)
        self._slider_rect = pygame.Rect(
            self.canvas_W + slider_x_virtual,
            scrollable_start + slider_y_virtual - self.panel_scroll_offset,
            slider_w, thumb_radius * 2
        )
        
        y = slider_y_virtual + int(20 * ui_scale)

        # Controls
        sep(8)
        lbl("-- Controls --", PANEL_DIM, 4)
        
        controls = [
            ("LMB drag",  "Paint / Place goal"),
            ("RMB drag",  "Erase / Remove goal"),
            ("MMB drag",  "Pan"),
            ("Alt+drag",  "Pan (laptop)"),
            ("Scroll",    "Zoom (canvas) / Scroll (panel)"),
            ("Slider",    "UI Scale"),
            ("[ / ]",     "Brush size"),
            ("Tab",       "Toggle mode"),
            ("Ctrl+Z/Y",  "Undo / Redo"),
            ("S",         "Save"),
            ("Ctrl+S",    "Save as..."),
            ("L",         "Load"),
            ("R",         "Reset view"),
            ("Del",       "Clear all"),
        ]
        
        for key, desc in controls:
            s1 = self.font_s.render(f"{key:<10}", True, (160,185,255))
            s2 = self.font_s.render(desc, True, PANEL_DIM)
            virtual_surf.blit(s1, (bx_virtual, y))
            virtual_surf.blit(s2, (bx_virtual + int(80 * ui_scale), y))
            y += self.font_s.get_height() + int(2 * ui_scale)
        
        # Store content height
        self.panel_content_height = y + int(20 * ui_scale)
        
        # Clamp scroll
        max_scroll = max(0, self.panel_content_height - scrollable_height)
        self.panel_scroll_offset = max(0, min(self.panel_scroll_offset, max_scroll))
        
        # Blit scrollable portion
        source_rect = pygame.Rect(0, self.panel_scroll_offset, panel_w, scrollable_height)
        self.screen.blit(virtual_surf, (self.canvas_W, scrollable_start), source_rect)
        
        # Draw scrollbar if needed
        if self.panel_content_height > scrollable_height:
            self._draw_scrollbar(panel_w, scrollable_start, scrollable_height)
    
    def _draw_scrollbar(self, panel_w, start_y, height):
        """Draw vertical scrollbar on panel"""
        ui_scale = self._get_ui_scale()
        scrollbar_w = int(8 * ui_scale)
        scrollbar_x = self.canvas_W + panel_w - scrollbar_w - int(4 * ui_scale)
        
        # Track
        track_rect = pygame.Rect(scrollbar_x, start_y, scrollbar_w, height)
        pygame.draw.rect(self.screen, (40, 44, 56), track_rect, border_radius=4)
        
        # Thumb
        if self.panel_content_height > height:
            thumb_h = max(int(30 * ui_scale), int(height * height / self.panel_content_height))
            scroll_ratio = self.panel_scroll_offset / max(1, self.panel_content_height - height)
            thumb_y = start_y + int(scroll_ratio * (height - thumb_h))
            
            thumb_rect = pygame.Rect(scrollbar_x, thumb_y, scrollbar_w, thumb_h)
            pygame.draw.rect(self.screen, (BTN_ACTIVE if self._is_scrollbar_hovered() else (80, 88, 110)), 
                           thumb_rect, border_radius=4)
    
    def _is_scrollbar_hovered(self):
        """Check if mouse is over scrollbar"""
        mx, my = pygame.mouse.get_pos()
        ui_scale = self._get_ui_scale()
        panel_w = int(PANEL_W * ui_scale)
        scrollbar_w = int(8 * ui_scale)
        scrollbar_x = self.canvas_W + panel_w - scrollbar_w - int(4 * ui_scale)
        scrollable_start = self.btn_clear.rect.bottom + int(10 * ui_scale)
        
        return (scrollbar_x <= mx < scrollbar_x + scrollbar_w and 
                scrollable_start <= my < self.H)
    
    def _get_scrollbar_thumb_rect(self):
        """Get scrollbar thumb rect for interaction"""
        ui_scale = self._get_ui_scale()
        panel_w = int(PANEL_W * ui_scale)
        scrollbar_w = int(8 * ui_scale)
        scrollbar_x = self.canvas_W + panel_w - scrollbar_w - int(4 * ui_scale)
        
        scrollable_start = self.btn_clear.rect.bottom + int(10 * ui_scale)
        scrollable_height = self.H - scrollable_start
        
        if self.panel_content_height <= scrollable_height:
            return None
        
        thumb_h = max(int(30 * ui_scale), int(scrollable_height * scrollable_height / self.panel_content_height))
        scroll_ratio = self.panel_scroll_offset / max(1, self.panel_content_height - scrollable_height)
        thumb_y = scrollable_start + int(scroll_ratio * (scrollable_height - thumb_h))
        
        return pygame.Rect(scrollbar_x, thumb_y, scrollbar_w, thumb_h)
    def _update_scale_from_mouse(self, mx):
        """Update scale preview based on mouse x position on slider"""
        if not hasattr(self, '_slider_rect'):
            return
        
        # Calculate new scale (0.5x to 3.0x)
        normalized = (mx - self._slider_rect.x) / self._slider_rect.w
        normalized = max(0.0, min(1.0, normalized))
        new_scale = 0.5 + normalized * (3.0 - 0.5)
        
        # Store preview scale (don't apply until mouse up)
        self.scale_slider_preview = new_scale
    
    def _apply_scale_change(self):
        """Apply the previewed scale change"""
        if self.scale_slider_preview is None:
            return
        
        # Update scale and rebuild UI
        self.renderer.dims.scale = self.scale_slider_preview
        self.scale_slider_preview = None
        self._update_fonts()
        
        # Update canvas width with new scale
        ui_scale = self._get_ui_scale()
        self.canvas_W = self.W - int(PANEL_W * ui_scale)
        self.renderer.canvas_W = self.canvas_W
        self._build_ui()
    
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            elif event.type == pygame.VIDEORESIZE:
                self.W, self.H = event.w, event.h
                ui_scale = self._get_ui_scale()
                self.canvas_W  = self.W - int(PANEL_W * ui_scale)
                self.renderer.canvas_W = self.canvas_W
                self._build_ui()

            elif event.type == pygame.KEYDOWN:
                if not self._on_key(event): return False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.pos[0] >= self.canvas_W: self._on_panel_click(event)
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
                    scrollable_start = self.btn_clear.rect.bottom + int(10 * ui_scale)
                    scrollable_height = self.H - scrollable_start
                    
                    dy = event.pos[1] - self.scrollbar_drag_start_y
                    thumb_h = max(int(30 * ui_scale), int(scrollable_height * scrollable_height / self.panel_content_height))
                    scroll_range = scrollable_height - thumb_h
                    content_range = self.panel_content_height - scrollable_height
                    
                    if scroll_range > 0:
                        scroll_delta = dy * content_range / scroll_range
                        self.panel_scroll_offset = self.scrollbar_drag_start_scroll + scroll_delta
                
                elif self.scale_slider_dragging:
                    self._update_scale_from_mouse(event.pos[0])
                elif self.renderer.panning:
                    self.renderer.update_pan(event.pos)
                elif event.pos[0] < self.canvas_W:
                    if   self.drawing: self.paint(event.pos[0], event.pos[1])
                    elif self.erasing: self.paint(event.pos[0], event.pos[1], erase=True)

            elif event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                if mx < self.canvas_W:
                    # Zoom canvas
                    self.renderer.zoom(event.y, mx, my)
                else:
                    # Scroll panel
                    ui_scale = self._get_ui_scale()
                    scroll_amount = int(30 * ui_scale)
                    self.panel_scroll_offset -= event.y * scroll_amount

        return True

    def _on_key(self, event):
        ctrl = pygame.key.get_mods() & pygame.KMOD_CTRL
        k    = event.key
        if k == pygame.K_z and ctrl:
            self.undo()
        elif k == pygame.K_y and ctrl:
            self.redo()
        elif k == pygame.K_s:
            if ctrl or self.current_file is None: self.save(force_dialog=True)
            else:                                  self.save(self.current_file)
        elif k == pygame.K_l:   self.load()
        elif k == pygame.K_TAB: self.mode = MODE_GOAL if self.mode==MODE_DRAW else MODE_DRAW
        elif k == pygame.K_LEFTBRACKET:  self.brush_cells = max(0, self.brush_cells - 1)
        elif k == pygame.K_RIGHTBRACKET: self.brush_cells = min(500, self.brush_cells + 1)
        elif k == pygame.K_r:   self.renderer.reset_view()
        elif k in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self._push_history()
            self.renderer.obstacles.clear(); self.goals.clear()
            self._status("Cleared all obstacles and goals.")
        elif k == pygame.K_ESCAPE: return False
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
        if   self.btn_draw.hit(event):   self.mode = MODE_DRAW
        elif self.btn_goal.hit(event):   self.mode = MODE_GOAL
        elif self.btn_save.hit(event):
            self.save(self.current_file if self.current_file else None)
        elif self.btn_saveas.hit(event): self.save(force_dialog=True)
        elif self.btn_load.hit(event):   self.load()
        elif self.btn_undo.hit(event):   self.undo()
        elif self.btn_redo.hit(event):   self.redo()
        elif self.btn_clear.hit(event):
            self._push_history()
            self.renderer.obstacles.clear(); self.goals.clear()
            self._status("Cleared all obstacles and goals.")

    def _on_canvas_press(self, event):
        mx, my = event.pos
        alt_held = bool(pygame.key.get_mods() & pygame.KMOD_ALT)
        if event.button == 2 or (event.button == 1 and alt_held):
            self.renderer.start_pan(event.pos)
        elif self.mode == MODE_DRAW:
            if   event.button == 1:
                self._push_history()
                self._last_paint_pos = None
                self.drawing = True; self.paint(mx, my)
            elif event.button == 3:
                self._push_history()
                self._last_paint_pos = None
                self.erasing = True; self.paint(mx, my, erase=True)
        elif self.mode == MODE_GOAL:
            if   event.button == 1:
                self._push_history()
                self.place_goal(mx, my)
            elif event.button == 3:
                self._push_history()
                self.remove_nearest_goal(mx, my)

    def run(self):
        while True:
            self.clock.tick(60)
            if not self.handle_events(): break
            self.draw()
        pygame.quit(); sys.exit(0)


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="5 cm/cell grid map editor")
    p.add_argument("file", nargs="?", help="JSON map file to open on startup")
    args = p.parse_args()
    editor = MapEditor()
    if args.file and os.path.isfile(args.file):
        editor.load(args.file)
    editor.run()

if __name__ == "__main__":
    main()