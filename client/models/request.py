from pydantic import BaseModel, Field, model_validator

from ..capabilities import models_for, unsupported_parameters
from ..enums import Level, Model, Parameter, TempUnit


class ForecastRequest(BaseModel):
    lat: float = Field(
        ..., ge=-90, le=90, description="Latitude in decimal degrees (-90 to 90)"
    )
    lon: float = Field(
        ..., ge=-180, le=180, description="Longitude in decimal degrees (-180 to 180)"
    )
    model: Model = Field(..., description="Forecast model")
    parameters: list[Parameter] = Field(
        ..., min_length=1, description="Requested forecast parameters"
    )
    levels: list[Level] = Field(
        default=[Level.surface], description="Geopotential altitude levels"
    )
    temp_unit: TempUnit = Field(
        default=TempUnit.kelvin, description="Unit for temperature values"
    )

    @model_validator(mode="after")
    def _check_model_provides_something(self) -> "ForecastRequest":
        """Reject a request the selected model cannot answer at all.

        Windy replies 204 with no body when a model provides none of the
        requested parameters, which tells the caller nothing about how to fix
        the call. Catching it here names the models that would work. A partial
        mismatch is left alone: the request still returns useful series, and the
        response carries a note about the parameters the model omitted.
        """
        missing = unsupported_parameters(self.model, self.parameters)
        if len(missing) < len(self.parameters):
            return self
        details = "; ".join(
            f"'{p}' needs one of: {', '.join(models_for(p)) or 'no known model'}"
            for p in missing
        )
        raise ValueError(
            f"Model '{self.model}' provides none of the requested parameters "
            f"({', '.join(str(p) for p in self.parameters)}). {details}"
        )
