package ai.nivesh.app.ui.advisor;

import ai.nivesh.app.data.repo.AdvisorRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class AdvisorViewModel_Factory implements Factory<AdvisorViewModel> {
  private final Provider<AdvisorRepository> repositoryProvider;

  public AdvisorViewModel_Factory(Provider<AdvisorRepository> repositoryProvider) {
    this.repositoryProvider = repositoryProvider;
  }

  @Override
  public AdvisorViewModel get() {
    return newInstance(repositoryProvider.get());
  }

  public static AdvisorViewModel_Factory create(Provider<AdvisorRepository> repositoryProvider) {
    return new AdvisorViewModel_Factory(repositoryProvider);
  }

  public static AdvisorViewModel newInstance(AdvisorRepository repository) {
    return new AdvisorViewModel(repository);
  }
}
