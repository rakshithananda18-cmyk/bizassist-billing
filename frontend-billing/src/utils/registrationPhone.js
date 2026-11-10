const COUNTRIES = {
  India: { code: '91', min: 10, max: 10 },
  'United States': { code: '1', min: 10, max: 10 },
  'United Kingdom': { code: '44', min: 10, max: 10 },
  Singapore: { code: '65', min: 8, max: 8 },
  UAE: { code: '971', min: 9, max: 9 },
}

export function normalizeRegistrationPhone(value, country = 'India') {
  const raw = String(value || '').trim()
  if (!raw || !/^\+?[0-9 ()\-.]+$/.test(raw)) throw new Error('Enter a valid phone number to create your account.')
  let digits = raw.replace(/[^0-9]/g, '')
  if (!raw.startsWith('+')) {
    const spec = COUNTRIES[country] || COUNTRIES.India
    if (digits.startsWith(spec.code) && digits.length === spec.code.length + spec.max) digits = digits.slice(spec.code.length)
    if (country !== 'India' && digits.startsWith('0')) digits = digits.slice(1)
    if (digits.length < spec.min || digits.length > spec.max) throw new Error(`Enter a valid phone number for ${country}, or include its country code.`)
    digits = spec.code + digits
  }
  if (digits.length < 8 || digits.length > 15 || digits.startsWith('0') || new Set(digits).size === 1
    || (digits.startsWith('91') && digits.length !== 12)) throw new Error('Enter a valid phone number including its country code.')
  return `+${digits}`
}
