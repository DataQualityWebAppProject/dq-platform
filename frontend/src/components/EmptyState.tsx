import { InboxIcon } from 'lucide-react'

interface EmptyStateProps {
  title: string
  description?: string
  icon?: React.ReactNode
  action?: {
    label: string
    onClick: () => void
  }
}

export default function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      <div className="text-gray-500 mb-4">
        {icon || <InboxIcon className="h-12 w-12" />}
      </div>
      <h3 className="text-lg font-medium text-gray-300">{title}</h3>
      {description && <p className="mt-1 text-sm text-gray-500 text-center max-w-sm">{description}</p>}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
