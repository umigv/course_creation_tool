#!/usr/bin/env python3
"""
UI elements with automatic sizing based on text content.
Ensures text never clips out of buttons or labels.
"""

import pygame


class UIButton:
    """Button that automatically sizes to fit its text"""
    
    def __init__(self, text, font, 
                 padding_x=10, padding_y=5,
                 bg_color=(200, 200, 200),
                 text_color=(0, 0, 0),
                 hover_color=None,
                 active_color=None,
                 border_radius=5,
                 alpha=255):
        """
        Create a button that sizes to fit text.
        
        Args:
            text: Button text
            font: pygame.Font object
            padding_x: Horizontal padding around text
            padding_y: Vertical padding around text
            bg_color: Background color (r, g, b)
            text_color: Text color (r, g, b)
            hover_color: Color when hovered (None = same as bg_color)
            active_color: Color when pressed (None = darker bg_color)
            border_radius: Corner radius
            alpha: Transparency (0-255)
        """
        self.text = text
        self.font = font
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.bg_color = bg_color
        self.text_color = text_color
        self.hover_color = hover_color or bg_color
        self.active_color = active_color or tuple(max(0, c - 30) for c in bg_color)
        self.border_radius = border_radius
        self.alpha = alpha
        
        self.rect = None
        self.is_hovered = False
        self.is_pressed = False
        
        # Pre-render text to get size
        self._update_text()
    
    def _update_text(self):
        """Update text surface and calculate dimensions"""
        self.text_surface = self.font.render(self.text, True, self.text_color)
        
        # Calculate button size based on text
        text_w, text_h = self.text_surface.get_size()
        self.width = text_w + 2 * self.padding_x
        self.height = text_h + 2 * self.padding_y
    
    def set_text(self, text):
        """Update button text and resize"""
        self.text = text
        self._update_text()
    
    def set_position(self, x, y):
        """Set button position (top-left corner)"""
        self.rect = pygame.Rect(x, y, self.width, self.height)
    
    def draw(self, surface):
        """Draw button on surface"""
        if not self.rect:
            return
        
        # Determine color based on state
        if self.is_pressed:
            color = self.active_color
        elif self.is_hovered:
            color = self.hover_color
        else:
            color = self.bg_color
        
        # Create surface with alpha
        button_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        
        # Draw background with rounded corners
        color_with_alpha = (*color, self.alpha)
        pygame.draw.rect(button_surface, color_with_alpha, 
                        (0, 0, self.width, self.height),
                        border_radius=self.border_radius)
        
        # Draw text centered
        text_x = self.padding_x
        text_y = self.padding_y
        button_surface.blit(self.text_surface, (text_x, text_y))
        
        # Blit to screen
        surface.blit(button_surface, self.rect.topleft)
    
    def handle_event(self, event):
        """
        Handle mouse events. Returns True if clicked.
        
        Args:
            event: pygame event
            
        Returns:
            bool: True if button was clicked (mouse up)
        """
        if not self.rect:
            return False
        
        if event.type == pygame.MOUSEMOTION:
            self.is_hovered = self.rect.collidepoint(event.pos)
        
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.is_pressed = True
        
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_pressed = self.is_pressed
            self.is_pressed = False
            if was_pressed and self.rect.collidepoint(event.pos):
                return True
        
        return False
    
    def contains_point(self, pos):
        """Check if point is inside button"""
        return self.rect and self.rect.collidepoint(pos)


class UILabel:
    """Text label with auto-sized background"""
    
    def __init__(self, text, font,
                 padding_x=10, padding_y=5,
                 bg_color=(255, 255, 255),
                 text_color=(0, 0, 0),
                 border_radius=3,
                 alpha=200):
        """
        Create a label that sizes to fit text.
        
        Args:
            text: Label text
            font: pygame.Font object
            padding_x: Horizontal padding around text
            padding_y: Vertical padding around text
            bg_color: Background color (r, g, b)
            text_color: Text color (r, g, b)
            border_radius: Corner radius
            alpha: Transparency (0-255)
        """
        self.text = text
        self.font = font
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.bg_color = bg_color
        self.text_color = text_color
        self.border_radius = border_radius
        self.alpha = alpha
        
        self.rect = None
        self._update_text()
    
    def _update_text(self):
        """Update text surface and calculate dimensions"""
        self.text_surface = self.font.render(self.text, True, self.text_color)
        
        # Calculate label size based on text
        text_w, text_h = self.text_surface.get_size()
        self.width = text_w + 2 * self.padding_x
        self.height = text_h + 2 * self.padding_y
    
    def set_text(self, text):
        """Update label text and resize"""
        self.text = text
        self._update_text()
    
    def set_position(self, x, y):
        """Set label position (top-left corner)"""
        self.rect = pygame.Rect(x, y, self.width, self.height)
    
    def draw(self, surface):
        """Draw label on surface"""
        if not self.rect:
            return
        
        # Create surface with alpha
        label_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        
        # Draw background with rounded corners
        color_with_alpha = (*self.bg_color, self.alpha)
        pygame.draw.rect(label_surface, color_with_alpha,
                        (0, 0, self.width, self.height),
                        border_radius=self.border_radius)
        
        # Draw text centered
        text_x = self.padding_x
        text_y = self.padding_y
        label_surface.blit(self.text_surface, (text_x, text_y))
        
        # Blit to screen
        surface.blit(label_surface, self.rect.topleft)


class UILabelGroup:
    """Group of labels with consistent styling, auto-stacked vertically"""
    
    def __init__(self, font, margin=5, spacing=2, **label_kwargs):
        """
        Create a label group.
        
        Args:
            font: pygame.Font object
            margin: Margin from screen edge
            spacing: Spacing between labels
            **label_kwargs: Additional arguments passed to UILabel
        """
        self.font = font
        self.margin = margin
        self.spacing = spacing
        self.label_kwargs = label_kwargs
        self.labels = []
    
    def set_texts(self, texts):
        """Set label texts (list of strings)"""
        self.labels = [
            UILabel(text, self.font, **self.label_kwargs)
            for text in texts
        ]
    
    def update_positions(self, x=None, y=None):
        """Update label positions. If x or y is None, uses margin."""
        if x is None:
            x = self.margin
        if y is None:
            y = self.margin
        
        current_y = y
        for label in self.labels:
            label.set_position(x, current_y)
            current_y += label.height + self.spacing
    
    def draw(self, surface):
        """Draw all labels"""
        for label in self.labels:
            label.draw(surface)


class UISlider:
    """
    Slider control with auto-sized label.
    """
    
    def __init__(self, label_text, font,
                 min_value=0.5, max_value=3.0, initial_value=1.0,
                 width=200, height=30,
                 scale_factor=1.0):
        """
        Create a slider with label.
        
        Args:
            label_text: Base label text (value will be appended)
            font: pygame.Font for label
            min_value: Minimum slider value
            max_value: Maximum slider value
            initial_value: Starting value
            width: Slider track width (in scaled pixels)
            height: Total slider height (in scaled pixels)
            scale_factor: UI scale factor
        """
        self.label_text = label_text
        self.font = font
        self.min_value = min_value
        self.max_value = max_value
        self.value = initial_value
        self.width = int(width * scale_factor)
        self.height = int(height * scale_factor)
        self.scale_factor = scale_factor
        
        self.rect = None
        self.dragging = False
        self.preview_value = None
        
        # Create label with initial value
        self.label_font = pygame.font.SysFont("monospace", int(11 * scale_factor))
        self._update_label()
    
    def _update_label(self):
        """Update label with current value"""
        display_value = self.preview_value if self.preview_value is not None else self.value
        label_text = f"{self.label_text}: {display_value:.2f}x"
        self.label = UILabel(
            label_text,
            self.label_font,
            padding_x=int(8 * self.scale_factor),
            padding_y=int(4 * self.scale_factor),
            bg_color=(255, 255, 255),
            text_color=(0, 0, 0),
            alpha=200
        )
    
    def set_position(self, x, y):
        """Set slider position (top-left of entire widget)"""
        self.rect = pygame.Rect(x, y, self.width, self.height)
        
        # Position label above slider
        label_y = y - self.label.height - int(5 * self.scale_factor)
        self.label.set_position(x, label_y)
    
    def draw(self, surface):
        """Draw slider"""
        if not self.rect:
            return
        
        # Draw background
        bg_padding = int(10 * self.scale_factor)
        bg_top_pad = int(25 * self.scale_factor)
        bg_bottom_pad = int(15 * self.scale_factor)
        
        # Calculate background size to fit label
        bg_width = max(self.width, self.label.width) + bg_padding * 2
        bg_height = self.height + bg_top_pad + bg_bottom_pad
        bg_x = self.rect.x - bg_padding
        bg_y = self.rect.y - bg_top_pad
        
        bg_surface = pygame.Surface((bg_width, bg_height), pygame.SRCALPHA)
        bg_surface.fill((255, 255, 255, 200))
        surface.blit(bg_surface, (bg_x, bg_y))
        
        # Update and draw label
        self._update_label()
        self.label.draw(surface)
        
        # Draw slider track
        track_y_offset = int(10 * self.scale_factor)
        track_h = int(4 * self.scale_factor)
        track_rect = pygame.Rect(
            self.rect.x,
            self.rect.y + track_y_offset,
            self.width,
            track_h
        )
        pygame.draw.rect(surface, (180, 180, 180), track_rect, border_radius=2)
        
        # Draw thumb
        display_value = self.preview_value if self.preview_value is not None else self.value
        normalized = (display_value - self.min_value) / (self.max_value - self.min_value)
        thumb_x = self.rect.x + int(normalized * self.width)
        thumb_y = self.rect.y + track_y_offset + track_h // 2
        thumb_radius = int(8 * self.scale_factor)
        
        thumb_color = (100, 150, 255) if self.dragging else (72, 136, 255)
        pygame.draw.circle(surface, thumb_color, (thumb_x, thumb_y), thumb_radius)
        pygame.draw.circle(surface, (255, 255, 255), (thumb_x, thumb_y),
                          thumb_radius - max(1, int(2 * self.scale_factor)))
    
    def handle_event(self, event):
        """
        Handle mouse events.
        
        Args:
            event: pygame event
            
        Returns:
            bool: True if value changed (on mouse up)
        """
        if not self.rect:
            return False
        
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.dragging = True
                self._update_value_from_mouse(event.pos[0])
        
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                self.dragging = False
                if self.preview_value is not None:
                    self.value = self.preview_value
                    self.preview_value = None
                return True
        
        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                self._update_value_from_mouse(event.pos[0])
        
        return False
    
    def _update_value_from_mouse(self, mx):
        """Update preview value based on mouse x position"""
        normalized = (mx - self.rect.x) / self.width
        normalized = max(0.0, min(1.0, normalized))
        self.preview_value = self.min_value + normalized * (self.max_value - self.min_value)
    
    def contains_point(self, pos):
        """Check if point is inside slider"""
        return self.rect and self.rect.collidepoint(pos)
    
    def get_value(self):
        """Get current slider value"""
        return self.value