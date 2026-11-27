from pydantic import BaseModel, Field


class NewTerminal(BaseModel):
    cols: int = Field(80, ge=1, le=1000, description="Columns of the terminal the browser shows")
    rows: int = Field(24, ge=1, le=500, description="Rows of the terminal the browser shows")


class Terminal(BaseModel):
    id: str
    started_at: float = Field(description="Unix time the shell started")
    attached: int = Field(description="Browser tabs watching it now")


class Terminals(BaseModel):
    terminals: list[Terminal]
