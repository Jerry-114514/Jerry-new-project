"""Invoke the fixed AutoDL shutdown file, including a validated ENOEXEC fallback.

Callers must first stop owned work and preserve required outputs. A returned
zero never proves provider billing stopped. No guard clocks are changed here.
"""
from additional_gpu_time_guard import request_shutdown
