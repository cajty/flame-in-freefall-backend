const METADATA_ZIP = /_metadata_.*\.zip$/i;
const METADATA_PATH = /(^|\/)metadata\//i;

// PSI keeps file revisions in added/modified/removed. The metadata bundle is
// the zip whose name contains _metadata_ and whose path is under metadata/.
export function findMetadataZip(record) {
  const files = ["added", "modified", "removed"].flatMap((key) =>
    Array.isArray(record?.[key]) ? record[key] : []
  );
  const candidates = files.filter(
    (file) =>
      typeof file?.file_name === "string" &&
      METADATA_ZIP.test(file.file_name) &&
      file.restricted !== true &&
      file.visible !== false
  );
  return (
    candidates.find((file) => METADATA_PATH.test(file.remote_path ?? "")) ??
    candidates.find((file) => /metadata/i.test(file.subcategory ?? "")) ??
    candidates[0] ??
    null
  );
}

export function looksLikeZip(buffer) {
  if (!buffer || buffer.length < 4) return false;
  return (
    buffer[0] === 0x50 &&
    buffer[1] === 0x4b &&
    ((buffer[2] === 0x03 && buffer[3] === 0x04) ||
      (buffer[2] === 0x05 && buffer[3] === 0x06))
  );
}
