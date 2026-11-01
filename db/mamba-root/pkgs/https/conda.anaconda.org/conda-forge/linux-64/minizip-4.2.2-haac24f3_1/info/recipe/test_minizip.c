#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include <mz.h>
#include <mz_os.h>
#include <mz_strm.h>
#include <mz_zip.h>
#include <mz_zip_rw.h>

int main(void) {
    static const char archive_path[] = "minizip-roundtrip.zip";
    static const char entry_name[] = "payload.txt";
    static const char payload[] = "minizip Windows ARM64 roundtrip";
    char output[sizeof(payload)] = {0};
    mz_zip_file file_info = {0};
    mz_zip_file *read_info = NULL;
    void *reader = NULL;
    void *writer = NULL;
    int result = 1;

    writer = mz_zip_writer_create();
    if (writer == NULL)
        goto cleanup;
    if (mz_zip_writer_open_file(writer, archive_path, 0, 0) != MZ_OK)
        goto cleanup;

    file_info.filename = entry_name;
    file_info.modified_date = time(NULL);
    file_info.version_madeby = MZ_VERSION_MADEBY;
    file_info.compression_method = MZ_COMPRESS_METHOD_DEFLATE;
    file_info.flag = MZ_ZIP_FLAG_UTF8;
    if (mz_zip_writer_add_buffer(writer, payload, (int32_t)sizeof(payload), &file_info) != MZ_OK)
        goto cleanup;
    if (mz_zip_writer_close(writer) != MZ_OK)
        goto cleanup;
    mz_zip_writer_delete(&writer);

    reader = mz_zip_reader_create();
    if (reader == NULL)
        goto cleanup;
    if (mz_zip_reader_open_file(reader, archive_path) != MZ_OK)
        goto cleanup;
    if (mz_zip_reader_goto_first_entry(reader) != MZ_OK)
        goto cleanup;
    if (mz_zip_reader_entry_get_info(reader, &read_info) != MZ_OK)
        goto cleanup;
    if (read_info == NULL || strcmp(read_info->filename, entry_name) != 0)
        goto cleanup;
    if (mz_zip_reader_entry_save_buffer_length(reader) != (int32_t)sizeof(payload))
        goto cleanup;
    if (mz_zip_reader_entry_save_buffer(reader, output, (int32_t)sizeof(output)) != MZ_OK)
        goto cleanup;
    if (memcmp(output, payload, sizeof(payload)) != 0)
        goto cleanup;

    result = 0;

cleanup:
    if (reader != NULL) {
        mz_zip_reader_close(reader);
        mz_zip_reader_delete(&reader);
    }
    if (writer != NULL) {
        mz_zip_writer_close(writer);
        mz_zip_writer_delete(&writer);
    }
    remove(archive_path);
    return result;
}
