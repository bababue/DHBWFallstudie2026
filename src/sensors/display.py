"""Four OLED views controlled by one debounced button."""

DOUBLE_CLICK_SECONDS = 0.4
LONG_PRESS_SECONDS = 1.0
STEP_PERCENT = 5

VIEWS = (("Sensoren", None), ("Licht", "led"),
         ("Wasser", "pump"), ("Luft", "fan"))


class ButtonMenu:
    def __init__(self, set_value):
        self.set_value = set_value
        self.view = 0
        self.pressed = False
        self.press_started = 0.0
        self.pending_until = None
        self.consumed = False

    def tick(self, pressed: bool, now: float, values: dict[str, int]) -> bool:
        """Return whether the visible view or a control value may have changed."""
        changed = False
        if self.pending_until is not None and now >= self.pending_until:
            self.pending_until = None
            device = VIEWS[self.view][1]
            if device is not None:
                self.set_value(device, min(100, values[device] + STEP_PERCENT))
                changed = True

        if pressed and not self.pressed:
            self.press_started = now
            self.consumed = False
            if self.pending_until is not None:
                self.pending_until = None
                self.consumed = True
                self.view = (self.view + 1) % len(VIEWS)
                changed = True
        elif pressed and self.pressed:
            device = VIEWS[self.view][1]
            if not self.consumed and device is not None and now - self.press_started >= LONG_PRESS_SECONDS:
                self.consumed = True
                self.pending_until = None
                self.set_value(device, 0)
                changed = True
        elif not pressed and self.pressed and not self.consumed:
            # A single click is applied only after the double-click window.
            if now - self.press_started < LONG_PRESS_SECONDS:
                self.pending_until = now + DOUBLE_CLICK_SECONDS

        self.pressed = pressed
        return changed
