"""Collection and processing of the London cycle hire dataset.

Modules here own the write side of the archive: polling TfL, publishing
snapshots to the Hub, compacting them into daily files, and maintaining the
versioned station history.
"""
