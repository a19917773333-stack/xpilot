"""Bounded recovery policy for a Chestnut link that disappears at runtime."""
from dataclasses import dataclass, field


def is_chestnut_link_error(exc: BaseException) -> bool:
  """Only transient USB/link errors are eligible for an automatic retry."""
  message = str(exc).lower()
  return "failed with -4" in message or "libusb_error_no_device" in message or "no such device" in message


@dataclass
class ChestnutRecovery:
  settle_time: float = 5.0
  _failed: bool = field(default=False, init=False)
  _ready_since: float | None = field(default=None, init=False)

  @property
  def pending(self) -> bool:
    return self._failed

  def failed(self) -> None:
    self._failed = True
    self._ready_since = None

  def ready(self, now: float, *, usb_ready: bool, safe_to_cycle: bool) -> bool:
    if not self._failed or not usb_ready or not safe_to_cycle:
      self._ready_since = None
      return False

    if self._ready_since is None:
      self._ready_since = now
      return False

    if now - self._ready_since < self.settle_time:
      return False

    self._failed = False
    self._ready_since = None
    return True
