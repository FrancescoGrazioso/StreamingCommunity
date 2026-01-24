/**
 * Series detail page - Episode selection logic
 */


export function selectAllEpisodes(seasonNumber) {
  const checkboxes = document.querySelectorAll(
    `input.episode-checkbox[data-season="${seasonNumber}"]`
  );
  checkboxes.forEach(cb => cb.checked = true);
  updateSelectedEpisodes(seasonNumber);
}

export function deselectAllEpisodes(seasonNumber) {
  const checkboxes = document.querySelectorAll(
    `input.episode-checkbox[data-season="${seasonNumber}"]`
  );
  checkboxes.forEach(cb => cb.checked = false);
  updateSelectedEpisodes(seasonNumber);
}

export function updateSelectedEpisodes(seasonNumber) {
  const checkboxes = document.querySelectorAll(
    `input.episode-checkbox[data-season="${seasonNumber}"]:checked`
  );
  const episodes = Array.from(checkboxes).map(cb => cb.value);
  
  let episodeString = '';
  
  if (episodes.length > 0) {
    const sortedEpisodes = episodes.map(Number).sort((a, b) => a - b);
    const ranges = [];
    let start = sortedEpisodes[0];
    let end = sortedEpisodes[0];
    
    for (let i = 1; i <= sortedEpisodes.length; i++) {
      if (i < sortedEpisodes.length && sortedEpisodes[i] === end + 1) {
        end = sortedEpisodes[i];
      } else {
        // Add range to results
        if (start === end) {
          ranges.push(String(start));
        } else if (end === start + 1) {
          ranges.push(String(start));
          ranges.push(String(end));
        } else {
          ranges.push(`${start}-${end}`);
        }
        
        if (i < sortedEpisodes.length) {
          start = sortedEpisodes[i];
          end = sortedEpisodes[i];
        }
      }
    }
    
    episodeString = ranges.join(',');
  }
  
  const inputField = document.getElementById(`selected_episodes_${seasonNumber}`);
  if (inputField) {
    inputField.value = episodeString;
  }
}

export function initEpisodeSelection() {
  const checkboxes = document.querySelectorAll('.episode-checkbox');
  
  checkboxes.forEach(cb => {
    cb.addEventListener('change', function() {
      updateSelectedEpisodes(this.dataset.season);
    });
  });
}

export function initFormValidation() {
  const forms = document.querySelectorAll('form[id^="form-season-"]');
  
  forms.forEach(form => {
    form.addEventListener('submit', function(e) {
      const seasonNumber = this.querySelector('input[name="season_number"]').value;
      const selectedEpisodes = document.getElementById(`selected_episodes_${seasonNumber}`).value;
      
      if (!selectedEpisodes) {
        e.preventDefault();
        alert('Seleziona almeno un episodio!');
      }
    });
  });
}

export function init() {
  initEpisodeSelection();
  initFormValidation();
}

if (typeof window !== 'undefined') {
  window.selectAllEpisodes = selectAllEpisodes;
  window.deselectAllEpisodes = deselectAllEpisodes;
}