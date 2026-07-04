from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import StepKind


class RecipeStepCreate(BaseModel):
    position: int = Field(ge=1)
    name: str
    kind: StepKind
    command: str | None = None
    config: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_step(self) -> "RecipeStepCreate":
        if self.kind == StepKind.COMMAND and not self.command:
            raise ValueError("command steps require a command")
        return self


class RecipeCreate(BaseModel):
    service_id: int
    name: str
    description: str = ""
    steps: list[RecipeStepCreate] = Field(min_length=1)


class RecipeUpdate(BaseModel):
    name: str
    description: str = ""
    steps: list[RecipeStepCreate] = Field(min_length=1)



class RecipeStepResponse(RecipeStepCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class RecipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_id: int
    name: str
    description: str
    steps: list[RecipeStepResponse]
