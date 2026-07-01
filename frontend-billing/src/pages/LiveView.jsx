import React from 'react'
import Sales from './Sales'

export default function LiveView(props) {
  return <Sales key="live-view" isLiveViewMode={true} {...props} />
}
