export const isRetiredBusiness = row => Boolean(row?.counterparty_deleted || row?.buyer_deleted || row?.seller_deleted)
