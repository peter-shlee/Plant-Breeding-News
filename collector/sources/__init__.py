from .rda import RdaSource
from .nics import NicsSource
from .nihhs import NihhsSource
from .seedworld import SeedWorldSource
from .sciencedaily import ScienceDailyAgFoodSource

SOURCES = {
    "rda": RdaSource,
    "nics": NicsSource,
    "nihhs": NihhsSource,
    "seedworld": SeedWorldSource,
    "sciencedaily": ScienceDailyAgFoodSource,
}
