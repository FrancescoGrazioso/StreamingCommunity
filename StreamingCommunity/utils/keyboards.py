# 24.01.26

import os
import sys


# Platform-specific imports for keyboard input
if os.name == "nt":
    import msvcrt
else:
    import tty
    import termios


def get_key():
    """Cross-platform keyboard input handler"""
    if os.name == "nt":
        
        # Windows
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):  # Special key
            ch2 = msvcrt.getwch()
            codes = {
                72: 'UP',
                80: 'DOWN',
                75: 'LEFT',
                77: 'RIGHT'
            }
            return codes.get(ord(ch2), None)
        
        if ch == '\r':
            return 'ENTER'
        if ch == '\x1b':
            return 'ESC'
        if ch == ' ':
            return 'SPACE'
        
        return ch
    
    else:
        
        # Linux / macOS
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch1 = sys.stdin.read(1)
            
            if ch1 == '\x1b':  # Escape sequence

                # Read the rest of the escape sequence without timeout
                # Most terminals send escape sequences as a complete unit
                ch2 = sys.stdin.read(1)
                if ch2 in ['[', 'O']:
                    ch3 = sys.stdin.read(1)
                    arrows = {
                        'A': 'UP',
                        'B': 'DOWN',
                        'C': 'RIGHT',
                        'D': 'LEFT'
                    }
                    result = arrows.get(ch3, None)
                    if result:
                        return result
                    
                # If we got here, it's a real ESC key
                return 'ESC'
            
            if ch1 == '\r' or ch1 == '\n':
                return 'ENTER'
            if ch1 == ' ':
                return 'SPACE'
            
            # Ignore other keys
            return None
        
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)