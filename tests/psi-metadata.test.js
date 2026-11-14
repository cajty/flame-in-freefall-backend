import assert from "node:assert/strict";
import test from "node:test";
import { findMetadataZip, looksLikeZip } from "../scripts/lib/psi-metadata.js";

test("findMetadataZip prefers the metadata folder", () => {
  const record = {
    added: [
      {
        file_name: "PSI-102_Engineering Documents.zip",
        remote_path: "/Home/psi-data/PSI-102/Engineering Documents/file.zip",
      },
      {
        file_name: "PSI-102_metadata_PSI-170_SAME.zip",
        remote_path: "/Home/psi-data/PSI-102/metadata/PSI-102_metadata_PSI-170_SAME.zip",
      },
    ],
  };

  assert.equal(findMetadataZip(record).file_name, "PSI-102_metadata_PSI-170_SAME.zip");
});

test("findMetadataZip ignores restricted, hidden and non-metadata zips", () => {
  const record = {
    added: [
      { file_name: "PSI-1_metadata_A.zip", restricted: true },
      { file_name: "PSI-1_metadata_B.zip", visible: false },
      { file_name: "PSI-1_data.zip" },
    ],
  };

  assert.equal(findMetadataZip(record), null);
});

test("looksLikeZip accepts ZIP local-file and empty-archive signatures", () => {
  assert.equal(looksLikeZip(Buffer.from([0x50, 0x4b, 0x03, 0x04])), true);
  assert.equal(looksLikeZip(Buffer.from([0x50, 0x4b, 0x05, 0x06])), true);
  assert.equal(looksLikeZip(Buffer.from("<!doctype html>")), false);
  assert.equal(looksLikeZip(Buffer.alloc(0)), false);
});
