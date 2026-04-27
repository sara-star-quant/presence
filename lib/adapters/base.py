from abc import ABC, abstractmethod


class Adapter(ABC):
    @abstractmethod
    def emit_context(self, event_name: str, text: str) -> None:
        """Emit context text to the host environment."""
        pass
