from .rda import RdaSource
from .nics import NicsSource
from .nihhs import NihhsSource

SOURCES = {
    "rda": RdaSource,
    "nics": NicsSource,
    "nihhs": NihhsSource,
}
