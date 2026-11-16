"""Everything that can go wrong online, as exceptions whose text is fit to show a player."""
from __future__ import annotations


class NetError(Exception):
    """Base class. ``str(error)`` is a sentence a player can read."""


class TransportError(NetError):
    """The connection itself failed."""


class WrongPasskey(TransportError):
    """The other side used a different passkey (or someone guessed wrongly)."""

    def __init__(self) -> None:
        super().__init__("The passkey didn't match.")


class TransportClosed(TransportError):
    """The connection to the server or the other player ended."""

    def __init__(self, detail: str = "") -> None:
        super().__init__("The connection was lost." + (f" ({detail})" if detail else ""))


class ServerUnreachable(TransportError):
    """Couldn't reach the mailbox server at all."""

    def __init__(self, url: str = "") -> None:
        super().__init__(
            "Couldn't reach the connection server. Check your internet connection "
            "or try again in a moment."
        )
        self.url = url


class ProtocolError(NetError):
    """The other side sent something malformed or out of order."""

    def __init__(self, detail: str = "unexpected message") -> None:
        super().__init__(f"The other player's game sent something unexpected ({detail}).")
        self.detail = detail


class Incompatible(NetError):
    """The two games speak different protocol versions."""

    def __init__(self) -> None:
        super().__init__("Your games are different versions. Update both with `rps --update`.")


class Cancelled(NetError):
    """The player pressed Esc."""

    def __init__(self) -> None:
        super().__init__("Cancelled.")


class Timeout(NetError):
    """Nothing arrived in time."""

    def __init__(self, what: str = "the other player") -> None:
        super().__init__(f"Timed out waiting for {what}.")


class RoomBurned(NetError):
    """Too many wrong passkeys: the host closed the room for safety."""

    def __init__(self) -> None:
        super().__init__(
            "Three wrong passkeys were tried, so this room was closed for safety. "
            "Create a new game to try again."
        )


class Declined(NetError):
    """The joiner didn't accept the game settings."""

    def __init__(self, who: str = "The other player") -> None:
        super().__init__(f"{who} declined the game.")


class PeerLeft(NetError):
    """The other player said goodbye."""

    def __init__(self, who: str = "The other player") -> None:
        super().__init__(f"{who} left the game.")


class ConnectionLost(NetError):
    """Nothing has been heard from the other player for too long."""

    def __init__(self, who: str = "the other player") -> None:
        super().__init__(f"Lost contact with {who}.")


class CheatDetected(NetError):
    """A revealed move didn't match what the player had locked in."""

    def __init__(self, who: str = "The other player") -> None:
        super().__init__(
            f"{who}'s game sent a move that doesn't match what they locked in, "
            "so the game was ended."
        )
