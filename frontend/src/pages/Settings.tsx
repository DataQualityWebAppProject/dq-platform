import { useState } from 'react'
import { Plus, Trash2, Bell, Shield, Users } from 'lucide-react'

interface NotificationRecipient {
  id: string
  email: string
  events: string[]
}

export default function Settings() {
  const [recipients, setRecipients] = useState<NotificationRecipient[]>([
    { id: '1', email: 'admin@company.com', events: ['validation_failed', 'anomaly_detected', 'cleaning_complete'] },
    { id: '2', email: 'analyst@company.com', events: ['validation_failed', 'report_generated'] },
    { id: '3', email: 'manager@company.com', events: ['report_generated'] },
  ])
  const [newEmail, setNewEmail] = useState('')

  const addRecipient = () => {
    if (!newEmail.trim()) return
    setRecipients([
      ...recipients,
      { id: String(Date.now()), email: newEmail, events: ['validation_failed'] },
    ])
    setNewEmail('')
  }

  const removeRecipient = (id: string) => {
    setRecipients(recipients.filter((r) => r.id !== id))
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-gray-400 text-sm mt-1">Platform configuration and notifications</p>
      </div>

      {/* Notifications Section */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Bell className="h-5 w-5 text-blue-400" />
          <h2 className="text-lg font-medium text-white">Notification Recipients</h2>
        </div>
        <p className="text-sm text-gray-400 mb-4">Manage who receives alerts for data quality events.</p>

        {/* Add Recipient */}
        <div className="flex gap-3 mb-6">
          <input
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="Enter email address"
            className="flex-1 max-w-md px-4 py-2.5 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => e.key === 'Enter' && addRecipient()}
          />
          <button
            onClick={addRecipient}
            className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>

        {/* Recipients List */}
        <div className="space-y-3">
          {recipients.map((recipient) => (
            <div key={recipient.id} className="flex items-center justify-between p-4 bg-gray-900/50 rounded-lg">
              <div>
                <p className="text-sm text-white font-medium">{recipient.email}</p>
                <div className="flex gap-2 mt-1">
                  {recipient.events.map((event) => (
                    <span key={event} className="px-2 py-0.5 bg-gray-700 text-gray-300 rounded text-xs">
                      {event.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              </div>
              <button
                onClick={() => removeRecipient(recipient.id)}
                className="p-2 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-lg transition-colors"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Security Section */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-6 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <Shield className="h-5 w-5 text-green-400" />
          <h2 className="text-lg font-medium text-white">Security</h2>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-lg">
            <div>
              <p className="text-sm text-white">MFA Enforcement</p>
              <p className="text-xs text-gray-400">Require multi-factor authentication for all users</p>
            </div>
            <div className="px-3 py-1 bg-green-900/30 text-green-300 rounded text-xs">Enabled</div>
          </div>
          <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-lg">
            <div>
              <p className="text-sm text-white">Session Timeout</p>
              <p className="text-xs text-gray-400">Automatically sign out after inactivity</p>
            </div>
            <span className="text-sm text-gray-300">30 minutes</span>
          </div>
          <div className="flex items-center justify-between p-4 bg-gray-900/50 rounded-lg">
            <div>
              <p className="text-sm text-white">Cognito User Pool</p>
              <p className="text-xs text-gray-400">AWS Cognito identity provider</p>
            </div>
            <span className="text-xs text-gray-400 font-mono">us-east-1_8KvqRmGSN</span>
          </div>
        </div>
      </div>

      {/* Team Section */}
      <div className="bg-gray-800 rounded-xl border border-gray-700 p-6">
        <div className="flex items-center gap-2 mb-4">
          <Users className="h-5 w-5 text-purple-400" />
          <h2 className="text-lg font-medium text-white">Team</h2>
        </div>
        <div className="space-y-3">
          {[
            { name: 'Admin User', email: 'admin@company.com', role: 'Admin' },
            { name: 'Data Analyst', email: 'analyst@company.com', role: 'Analyst' },
            { name: 'Viewer', email: 'viewer@company.com', role: 'Viewer' },
          ].map((user) => (
            <div key={user.email} className="flex items-center justify-between p-4 bg-gray-900/50 rounded-lg">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center text-sm text-gray-300">
                  {user.name[0]}
                </div>
                <div>
                  <p className="text-sm text-white">{user.name}</p>
                  <p className="text-xs text-gray-400">{user.email}</p>
                </div>
              </div>
              <span className="px-2 py-1 bg-gray-700 text-gray-300 rounded text-xs">{user.role}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
