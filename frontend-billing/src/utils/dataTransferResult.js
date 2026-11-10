// Imports can commit resolvable rows while returning skipped relationships.
// Every caller must inspect the result before reporting success or switching DBs.
export function assertCompleteImport(result) {
  const skipped = [...(Array.isArray(result?.b2b_skipped) ? result.b2b_skipped : []),
    ...(Array.isArray(result?.skipped_records) ? result.skipped_records : [])]
  if (result?.complete === false || skipped.length) {
    throw new Error(`Import incomplete: ${skipped.length || 'some'} record(s) could not be restored. Applied records are saved. Resolve the missing records or relationships and retry; hosting mode has not changed.`)
  }
}
