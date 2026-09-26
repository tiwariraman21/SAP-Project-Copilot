from dataclasses import dataclass


@dataclass
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def as_dict(self) -> dict:
        return {"model": self.model, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "total_tokens": self.total_tokens}


def response_usage(response, model: str) -> Usage:
    usage = getattr(response, "usage", None)
    return Usage(model=model, input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                 output_tokens=int(getattr(usage, "output_tokens", 0) or 0), total_tokens=int(getattr(usage, "total_tokens", 0) or 0))


class AIServiceError(RuntimeError):
    pass

