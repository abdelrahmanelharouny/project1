"""Errors local to the AI orchestration boundary."""


class AIOrchestrationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
