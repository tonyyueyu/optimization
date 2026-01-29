import React, { useState } from 'react';
import styles from './SettingsWindow.module.css';
import { X, User, Brush, Bot, Settings as SettingsIcon, Database, Link } from 'lucide-react'; // Using lucide-react icons

interface SettingsWindowProps {
  isOpen: boolean;
  onClose: () => void;
}

const SettingsWindow: React.FC<SettingsWindowProps> = ({ isOpen, onClose }) => {
  const [activeSection, setActiveSection] = useState('account');

  if (!isOpen) return null;

  // Prevent clicks inside the modal from closing it
  const handleModalContentClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.modalContent} onClick={handleModalContentClick}>
        <button className={styles.closeButton} onClick={onClose} aria-label="Close settings">
          <X size={20} />
        </button>
        <h2 className={styles.title}>Settings</h2>
        <div className={styles.layout}>
          <nav className={styles.sidebar}>
            <ul>
              <li 
                className={activeSection === 'account' ? styles.active : ''}
                onClick={() => setActiveSection('account')}
              >
                <User size={18} /> Account
              </li>
              <li 
                className={activeSection === 'appearance' ? styles.active : ''}
                onClick={() => setActiveSection('appearance')}
              >
                <Brush size={18} /> Appearance
              </li>
              <li 
                className={activeSection === 'customize' ? styles.active : ''}
                onClick={() => setActiveSection('customize')}
              >
                <SettingsIcon size={18} /> Customize
              </li>
              <li 
                className={activeSection === 'data' ? styles.active : ''}
                onClick={() => setActiveSection('data')}
              >
                <Database size={18} /> Data
              </li>
            </ul>
          </nav>
          <main className={styles.mainContent}>
            {activeSection === 'account' && (
              <>
                <h3>Account</h3>
                <p>Account settings to be implemented.</p>
              </>
            )}
            {activeSection === 'appearance' && (
              <>
                <h3>Appearance</h3>
                <p>Appearance settings to be implemented.</p>
              </>
            )}
            {activeSection === 'customize' && (
              <>
                <h3>Customize</h3>
                <p>Customization options to be implemented.</p>
              </>
            )}
            {activeSection === 'data' && (
              <>
                <h3>Data</h3>
                <p>Data settings to be implemented.</p>
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
};

export default SettingsWindow; 