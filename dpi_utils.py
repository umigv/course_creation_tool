#!/usr/bin/env python3
"""
Cross-platform DPI and GUI scale detection utilities.
Supports Ubuntu/Linux, Windows, and macOS.
"""

import os
import subprocess
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class ScaledWindowSize:
    width: int
    height: int
    scale: float


def get_system_scale_factor():
    """
    Detect system GUI scale factor across different platforms.
    
    Returns:
        float: Scale factor (1.0 = 100%, 2.0 = 200%, etc.)
    """
    system = platform.system()
    
    if system == "Linux":
        return _get_linux_scale_factor()
    elif system == "Windows":
        return _get_windows_scale_factor()
    elif system == "Darwin":  # macOS
        return _get_macos_scale_factor()
    else:
        return 1.0


def _get_linux_scale_factor():
    """Get scale factor on Linux (Ubuntu, GNOME, KDE, etc.)"""
    
    # Method 1: Check GDK_SCALE environment variable (GNOME/GTK)
    gdk_scale = os.environ.get('GDK_SCALE')
    if gdk_scale:
        try:
            return float(gdk_scale)
        except ValueError:
            pass
    
    # Method 2: Check QT_SCALE_FACTOR (KDE/Qt)
    qt_scale = os.environ.get('QT_SCALE_FACTOR')
    if qt_scale:
        try:
            return float(qt_scale)
        except ValueError:
            pass
    
    # Method 3: Try to get GNOME scaling factor via gsettings
    try:
        result = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'scaling-factor'],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            # Output is like "uint32 2" or just "2"
            output = result.stdout.strip()
            if 'uint32' in output:
                scale = int(output.split()[-1])
            else:
                scale = int(output)
            if scale > 0:
                return float(scale)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError, FileNotFoundError):
        pass
    
    # Method 4: Check Xft.dpi (X11 DPI setting)
    try:
        result = subprocess.run(
            ['xrdb', '-query'],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Xft.dpi:' in line:
                    try:
                        dpi = float(line.split(':')[1].strip())
                        # Standard DPI is 96, so scale factor is dpi/96
                        return dpi / 96.0
                    except (ValueError, IndexError):
                        pass
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 5: Try GDK_DPI_SCALE
    gdk_dpi_scale = os.environ.get('GDK_DPI_SCALE')
    if gdk_dpi_scale:
        try:
            return float(gdk_dpi_scale)
        except ValueError:
            pass
    
    return 1.0


def _get_windows_scale_factor():
    """Get scale factor on Windows"""
    try:
        import ctypes
        
        # Set DPI awareness
        try:
            # Windows 10 1607+ (Creators Update)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            try:
                # Windows Vista+
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass
        
        # Get DPI
        try:
            # Try to get DPI from primary monitor
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            
            # Standard Windows DPI is 96
            return dpi / 96.0
        except (AttributeError, OSError):
            pass
    except ImportError:
        pass
    
    return 1.0


def _get_macos_scale_factor():
    """Return SDL's logical-coordinate scale on macOS.

    SDL already maps logical window coordinates to Retina backing pixels.
    Multiplying the requested window size by the backing scale asks macOS for
    an oversized window and causes the OS to forcibly resize it.
    """
    return 1.0


def apply_scale_to_window_size(width, height, scale=None) -> ScaledWindowSize:
    """
    Apply scale factor to window dimensions.
    
    Args:
        width: Base width in logical pixels
        height: Base height in logical pixels
        scale: Scale factor (None = auto-detect)
        
    Returns:
        ScaledWindowSize: Scaled dimensions and the scale factor used
    """
    if scale is None:
        scale = get_system_scale_factor()
    
    return ScaledWindowSize(int(width * scale), int(height * scale), scale)


def setup_pygame_dpi_awareness():
    """
    Setup DPI awareness before pygame initialization.
    Call this before pygame.init()
    
    Returns:
        float: Detected scale factor
    """
    scale = get_system_scale_factor()
    
    # On Windows, set DPI awareness
    if platform.system() == "Windows":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (AttributeError, OSError):
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except (AttributeError, OSError):
                    pass
        except ImportError:
            pass
    
    return scale


if __name__ == "__main__":
    # Test the scale detection
    scale = get_system_scale_factor()
    print(f"Detected system scale factor: {scale}")
    print(f"Platform: {platform.system()}")
    
    # Test window size calculation
    base_w, base_h = 1200, 800
    scaled = apply_scale_to_window_size(base_w, base_h)
    print(f"\nBase window size: {base_w}x{base_h}")
    print(f"Scaled window size: {scaled.width}x{scaled.height}")
    print(f"Scale factor used: {scaled.scale}")
