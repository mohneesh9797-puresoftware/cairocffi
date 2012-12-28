"""
    cairocffi.surface
    ~~~~~~~~~~~~~~~~~

    Bindings for the various types of surface objects.

    :copyright: Copyright 2013 by Simon Sapin
    :license: BSD, see LICENSE for details.

"""

import sys
import ctypes

from . import ffi, cairo, _check_status


def _make_read_func(file_obj):
    @ffi.callback("cairo_read_func_t", error='READ_ERROR')
    def read_func(closure, data, length):
        string = file_obj.read(length)
        if len(string) < length:  # EOF too early
            return 'READ_ERROR'
        ffi.buffer(data, length)[:len(string)] = string
        return 'SUCCESS'
    return read_func


def _make_write_func(file_obj):
    @ffi.callback("cairo_write_func_t", error='WRITE_ERROR')
    def read_func(_closure, data, length):
        file_obj.write(ffi.buffer(data, length))
        return 'SUCCESS'
    return read_func


def _encode_filename(filename):
    if not isinstance(filename, bytes):
        filename = filename.encode(sys.getfilesystemencoding())
    return ffi.new('char[]', filename)


def from_buffer(data):
    return ffi.cast(
        'char *', ctypes.addressof(ctypes.c_char.from_buffer(data)))


class KeepAlive(object):
    """
    Keep some objects alive until a callback is called.
    :attr:`closure` is a tuple of cairo_destroy_func_t and void* cdata objects,
    as expected by cairo_surface_set_mime_data().

    """
    instances = set()

    def __init__(self, *objects):
        self.instances.add(self)
        self.objects = objects
        f = lambda _: self.instances.remove(self)
        self.closure = (ffi.callback('cairo_destroy_func_t', f), ffi.NULL)


class Surface(object):
    def __init__(self, handle):
        _check_status(cairo.cairo_surface_status(handle))
        self._handle = ffi.gc(handle, cairo.cairo_surface_destroy)

    @staticmethod
    def _from_handle(handle):
        surface = Surface(handle)
        surface_type = cairo.cairo_surface_get_type(handle)
        if surface_type in SURFACE_TYPE_TO_CLASS:
            surface.__class__ = SURFACE_TYPE_TO_CLASS[surface_type]
        return surface

    # XXX needs tests
    def copy_page(self):
        cairo.cairo_surface_copy_page(self._handle)

    def show_page(self):
        cairo.cairo_surface_show_page(self._handle)

    def create_similar(self, content, width, height):
        return Surface._from_handle(cairo.cairo_surface_create_similar(
            self._handle, content, width, height))

    def create_similar_image(self, content, width, height):
        return Surface._from_handle(cairo.cairo_surface_create_similar_image(
            self._handle, content, width, height))

    def finish(self):
        cairo.cairo_surface_finish(self._handle)

    def flush(self):
        cairo.cairo_surface_flush(self._handle)

    def get_content(self):
        return cairo.cairo_surface_get_content(self._handle)

    def get_device_offset(self):
        offsets = ffi.new('double[2]')
        cairo.cairo_surface_get_device_offset(
            self._handle, offsets + 0, offsets + 1)
        return tuple(offsets)

    def set_device_offset(self, x_offset, y_offset):
        cairo.cairo_surface_set_device_offset(self._handle, x_offset, y_offset)

    def get_fallback_resolution(self):
        ppi = ffi.new('double[2]')
        cairo.cairo_surface_get_fallback_resolution(
            self._handle, ppi + 0, ppi + 1)
        return tuple(ppi)

    def set_fallback_resolution(self, x_pixels_per_inch, y_pixels_per_inch):
        cairo.cairo_surface_get_fallback_resolution(
            self._handle, x_pixels_per_inch, y_pixels_per_inch)

    def get_font_options(self):
        raise NotImplementedError

    def get_mime_data(self, mime_type):
        buffer_address = ffi.new('char **')
        buffer_length = ffi.new('unsigned long *')
        mime_type = ffi.new('char *', mime_type.encode('utf8'))
        cairo.cairo_surface_get_mime_type(
            self._handle, mime_type, buffer_address, buffer_length)
        return ffi.buffer(buffer_address[0], buffer_length[0])

    def set_mime_data(self, mime_type, data):
        mime_type = ffi.new('char *', mime_type.encode('utf8'))
        cairo.cairo_surface_set_mime_type(
            self._handle, mime_type, from_buffer(data), len(data),
            *KeepAlive(data, mime_type).closure)

    def set_supports_mime_type(self, mime_type):
        mime_type = ffi.new('char *', mime_type.encode('utf8'))
        return bool(cairo.cairo_surface_supports_mime_type(
            self._handle, mime_type))

    def mark_dirty(self):
        return cairo.cairo_surface_mark_dirty(self._handle)

    def mark_dirty_rectangle(self, x, y, width, height):
        return cairo.cairo_surface_mark_dirty_rectangle(
            self._handle, x, y, width, height)

    def write_to_png(self, target):
        if hasattr(target, 'write'):
            write_func = _make_write_func(target)
            _check_status(cairo.cairo_surface_write_to_png_stream(
                self._handle, write_func, ffi.NULL))
        else:
            _check_status(cairo.cairo_surface_write_to_png(
                self._handle, _encode_filename(target)))


class ImageSurface(Surface):
    def __init__(self, format, width, height, data=None, stride=None):
        if data is None:
            handle = cairo.cairo_image_surface_create(format, width, height)
        else:
            if stride is None:
                stride = self.format_stride_for_width(format, width)
            if len(data) < stride * height:
                raise ValueError('Got a %d bytes buffer, needs at least %d.'
                                 % (len(data), stride * height))
            self._data = data  # keep it alive
            data = from_buffer(data)
            handle = cairo.cairo_image_surface_create_for_data(
                data, format, width, height, stride)
        Surface.__init__(self, handle)

    @staticmethod
    def format_stride_for_width(format, width):
        return cairo.cairo_format_stride_for_width(format, width)

    @classmethod
    def create_for_data(cls, data, format, width, height, stride=None):
        return cls(format, width, height, data, stride)

    @classmethod
    def create_from_png(cls, source):
        if hasattr(source, 'read'):
            read_func = _make_read_func(source)
            handle = cairo.cairo_image_surface_create_from_png_stream(
                read_func, ffi.NULL)
        else:
            handle = cairo.cairo_image_surface_create_from_png(
                _encode_filename(source))
        surface = Surface(handle)
        # XXX is there a cleaner way to bypass ImageSurface.__init__?
        surface.__class__ = cls
        return surface

    def get_data(self):
        return ffi.buffer(
            cairo.cairo_image_surface_get_data(self._handle),
            size=self.get_stride() * self.get_height())

    def get_format(self):
        return cairo.cairo_image_surface_get_format(self._handle)

    def get_width(self):
        return cairo.cairo_image_surface_get_width(self._handle)

    def get_height(self):
        return cairo.cairo_image_surface_get_height(self._handle)

    def get_stride(self):
        return cairo.cairo_image_surface_get_stride(self._handle)


SURFACE_TYPE_TO_CLASS = dict(
    IMAGE=ImageSurface,
)