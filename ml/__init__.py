"""MPLADS Sentinel - machine learning package.

Risk indicators for MPLADS works review. See CLAUDE.md for the leakage rule
and the honesty rules that govern every module here.
"""

import os as _os

# This host reports 28 logical cores, which is above the thread count OpenBLAS
# was compiled for, and joblib cannot probe physical cores on Windows. Both
# emit noisy warnings on every run. Capping the pool silences them and costs
# nothing: the pipeline is memory-bound, not thread-bound, at this size.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "LOKY_MAX_CPU_COUNT"):
    _os.environ.setdefault(_var, "16")

__version__ = "0.1.0"
